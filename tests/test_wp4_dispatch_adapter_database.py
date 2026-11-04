"""Real isolated PostgreSQL + coordinator; in-memory file double, NOT NTFS."""
from hashlib import sha256
import io
import json
import sys
import time
import unittest
from uuid import uuid4
import psycopg

import test_wp4_dispatch_database as foundation
from api.local_publication import AuthorizationDenied, PublicationUnknown, TargetConflict
from api.publication_dispatch import (
    DispatchUncertain, IsolatedPublicationDispatcher, IsolatedPublicationStore,
)


class MemoryFiles:
    """Explicit test double. No directories, handles, NTFS or OS crash proof."""
    def __init__(self):
        self.content = None
        self.installs = 0
        self.calls = 0
        self.before_install = None

    def reconcile(self, case, content, digest):
        self.calls += 1
        if self.content is None:
            return 'missing'
        if self.content != content:
            raise TargetConflict('Test collision')
        return 'matching'

    def publish(self, case, content, digest, authorize, checkpoint=None):
        self.calls += 1
        if not authorize():
            raise AuthorizationDenied('Test denial')
        if self.content is not None:
            if self.content != content:
                raise TargetConflict('Test collision')
            return 'reconciled'
        if checkpoint:
            checkpoint('staged')
        if self.before_install:
            self.before_install()
        if not authorize():
            raise AuthorizationDenied('Test denial')
        self.content = content
        self.installs += 1
        if checkpoint:
            checkpoint('installed')
        return 'created'


@unittest.skipUnless(foundation.CONFIG is not None, 'Private isolated database input required')
class AdapterDatabaseTests(foundation.DispatchDatabaseTests):
    def adapter(self, files=None, factory=None):
        files = files or MemoryFiles()
        factory = factory or (lambda: psycopg.connect(**foundation.CONFIG['worker']))
        store = IsolatedPublicationStore(factory, foundation.CONFIG['database'])
        return IsolatedPublicationDispatcher(store, files), files

    def prepare(self, dispatcher, action):
        result = dispatcher.step(action['action_id'], 'reconcile', 'reconcile-'+uuid4().hex)
        self.assertEqual(result['state'], 'retryable')
        return 'write-'+uuid4().hex

    def test_adapter_exact_bytes_commit_and_ten_no_effect_replays(self):
        action = self.fixture(); dispatcher, files = self.adapter()
        key = self.prepare(dispatcher, action)
        result = dispatcher.step(action['action_id'], 'write', key)
        self.assertEqual((result['state'], result['sequence'], result['write_attempts']), ('succeeded', 4, 1))
        self.assertEqual(files.content, foundation.CONFIG['base']['report'].encode())
        self.assertEqual(sha256(files.content).hexdigest(), action['content_sha256'])
        for _ in range(10):
            replay = dispatcher.step(action['action_id'], 'write', key)
            self.assertEqual(replay['state'], 'succeeded'); self.assertIsNone(replay['observation'])
        self.assertEqual((files.installs, files.calls), (1, 2))

    def test_adapter_existing_match_needs_no_write(self):
        action = self.fixture(); dispatcher, files = self.adapter()
        files.content = foundation.CONFIG['base']['report'].encode()
        result = dispatcher.step(action['action_id'], 'reconcile', 'existing-'+uuid4().hex)
        self.assertEqual((result['state'], result['write_attempts'], files.installs), ('succeeded', 0, 0))

    def test_adapter_abort_before_and_after_install_and_before_receipt_commit(self):
        for point in ('staged', 'installed', 'receipt_pending'):
            action = self.fixture(); dispatcher, files = self.adapter()
            key = self.prepare(dispatcher, action)
            def abort(name):
                if name == point:
                    raise SystemExit(77)
            with self.assertRaises(SystemExit):
                dispatcher.step(action['action_id'], 'write', key, checkpoint=abort)
            with self.worker() as conn:
                state = json.loads(conn.execute('SELECT retail.api_publication_state_v1(%s)',
                    (action['action_id'],)).fetchone()[0])
            self.assertEqual((state['state'], state['sequence']), ('in_progress', 3))
            self.assertEqual(files.installs, 0 if point == 'staged' else 1)
            recovered = dispatcher.step(action['action_id'], 'write', key)
            self.assertEqual(recovered['state'], 'succeeded'); self.assertEqual(files.installs, 1)

    def test_adapter_receipt_sql_fault_rolls_back_not_the_installed_file(self):
        action = self.fixture(); dispatcher, files = self.adapter(); key = self.prepare(dispatcher, action)
        self.admin.execute("CREATE FUNCTION pg_temp.fail_adapter_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF NEW.kind='observed' THEN RAISE EXCEPTION 'Synthetic receipt fault'; END IF; RETURN NEW; END $$")
        self.admin.execute('CREATE TRIGGER adapter_receipt_fault AFTER INSERT ON retail.publication_dispatch_events_v1 '
            'FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_adapter_receipt()')
        self.admin.commit()
        try:
            with self.assertRaises(DispatchUncertain) as error:
                dispatcher.step(action['action_id'], 'write', key)
            self.assertNotIn(foundation.CONFIG['worker']['password'], str(error.exception))
            self.assertEqual(files.installs, 1)
            with self.worker() as conn:
                state = json.loads(conn.execute('SELECT retail.api_publication_state_v1(%s)',
                    (action['action_id'],)).fetchone()[0])
            self.assertEqual((state['state'], state['sequence']), ('in_progress', 3))
        finally:
            self.admin.execute('DROP TRIGGER adapter_receipt_fault ON retail.publication_dispatch_events_v1')
            self.admin.commit()
        self.assertEqual(dispatcher.step(action['action_id'], 'write', key)['state'], 'succeeded')
        self.assertEqual(files.installs, 1)

    def test_adapter_lost_commit_ack_is_recovered_without_another_file_call(self):
        action = self.fixture(); dispatcher, files = self.adapter(); key = self.prepare(dispatcher, action)
        commits = [0]
        class LostAck:
            def __init__(self):
                self.conn = psycopg.connect(**foundation.CONFIG['worker'])
            def execute(self, *args): return self.conn.execute(*args)
            def rollback(self): return self.conn.rollback()
            def close(self): return self.conn.close()
            @property
            def autocommit(self): return self.conn.autocommit
            @property
            def read_only(self): return self.conn.read_only
            @read_only.setter
            def read_only(self, value): self.conn.read_only = value
            def commit(self):
                self.conn.commit(); commits[0] += 1
                if commits[0] == 2:
                    raise OSError('Synthetic lost acknowledgement after real commit')
        uncertain, _ = self.adapter(files, LostAck)
        with self.assertRaises(DispatchUncertain): uncertain.step(action['action_id'], 'write', key)
        calls = files.calls
        self.assertEqual(dispatcher.step(action['action_id'], 'write', key)['state'], 'succeeded')
        self.assertEqual((files.calls, files.installs), (calls, 1))

    def test_adapter_transaction_locks_block_revocation_and_competing_claims(self):
        action = self.fixture(); dispatcher, files = self.adapter(); key = self.prepare(dispatcher, action)
        seen = []
        def contention():
            with psycopg.connect(**foundation.CONFIG['admin']) as other:
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    other.execute('SELECT 1 FROM retail.owner_credentials WHERE reviewer_id=%s FOR UPDATE NOWAIT', (self.owner,))
                other.rollback()
            with self.worker() as other:
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    self.claim(other, action, key='competing-'+uuid4().hex)
                other.rollback()
            seen.append(True)
        files.before_install = contention
        self.assertEqual(dispatcher.step(action['action_id'], 'write', key)['state'], 'succeeded')
        self.assertEqual(seen, [True])

    def test_adapter_expiry_between_stage_and_install_never_installs(self):
        action = self.fixture(short=True); dispatcher, files = self.adapter(); key = self.prepare(dispatcher, action)
        files.before_install = lambda: time.sleep(2.2)
        result = dispatcher.step(action['action_id'], 'write', key)
        self.assertEqual((result['state'], result['observation'], files.installs), ('unknown', 'unknown', 0))
        cancelled = dispatcher.step(action['action_id'], 'reconcile', 'expired-'+uuid4().hex)
        self.assertEqual(cancelled['state'], 'cancelled')

    def test_adapter_expired_lease_recovery_is_readonly_even_after_original_deadline(self):
        action = self.fixture(short=True); dispatcher, files = self.adapter(); key = self.prepare(dispatcher, action)
        def abort(point):
            if point == 'installed': raise SystemExit(77)
        with self.assertRaises(SystemExit): dispatcher.step(action['action_id'], 'write', key, checkpoint=abort)
        time.sleep(30.1)
        calls = files.calls
        replay = dispatcher.step(action['action_id'], 'write', key)
        self.assertEqual((replay['state'], replay['observation'], files.calls), ('in_progress', None, calls))
        result = dispatcher.step(action['action_id'], 'reconcile', 'recover-'+uuid4().hex)
        self.assertEqual((result['state'], result['write_attempts'], files.installs), ('succeeded', 1, 1))

    def test_adapter_collision_and_unknown_never_blind_retry(self):
        action = self.fixture(); dispatcher, files = self.adapter()
        files.content = b'different'
        self.assertEqual(dispatcher.step(action['action_id'], 'reconcile', 'collision-'+uuid4().hex)['state'], 'dead_letter')
        action = self.fixture(); dispatcher, files = self.adapter(); key = self.prepare(dispatcher, action)
        def unknown(*args, **kwargs): raise PublicationUnknown('Synthetic uncertain file operation')
        files.publish = unknown
        self.assertEqual(dispatcher.step(action['action_id'], 'write', key)['state'], 'unknown')
        with self.assertRaises(DispatchUncertain): dispatcher.step(action['action_id'], 'write', 'blind-'+uuid4().hex)
        self.assertEqual(files.installs, 0)

    def test_adapter_zz_revoked_owner_after_claim_never_touches_write_target(self):
        action = self.fixture(); dispatcher, files = self.adapter(); key = self.prepare(dispatcher, action)
        calls = files.calls
        def revoke(point):
            if point == 'claim_committed':
                self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s', (self.owner,))
                self.admin.commit()
        result = dispatcher.step(action['action_id'], 'write', key, checkpoint=revoke)
        self.assertEqual((result['state'], files.calls, files.installs), ('unknown', calls, 0))
        cancelled = dispatcher.step(action['action_id'], 'reconcile', 'revoked-'+uuid4().hex)
        self.assertEqual((cancelled['state'], cancelled['write_attempts']), ('cancelled', 1))


if __name__ == '__main__':
    foundation.CONFIG = json.loads(sys.stdin.read())
    AdapterDatabaseTests.__unittest_skip__ = False
    names = [name for name in dir(AdapterDatabaseTests) if name.startswith('test_adapter_')]
    suite = unittest.TestSuite(AdapterDatabaseTests(name) for name in names)
    class PrivateResult(unittest.TextTestResult):
        error_types = []
        def addError(self, test, error):
            self.error_types.append(error[0].__name__); super().addError(test, error)
    result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=PrivateResult).run(suite)
    print(json.dumps({'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
        'failed_tests': [getattr(t, '_testMethodName', 'class_setup') for t, _ in result.errors + result.failures],
        'error_types': result.error_types}))
