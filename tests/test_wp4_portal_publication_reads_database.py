"""Private actual PostgreSQL adapter/ASGI checks, not a listening HTTP server."""
from hashlib import sha256
import io
import json
import re
import sys
import unittest
from uuid import uuid4

import psycopg
from fastapi import FastAPI, HTTPException

from api.portal import digest, session_csrf
from api.portal_publication import IsolatedPortalPublicationStore, PortalOutcomeUncertain, install_isolated_publication_reads
from test_wp4_portal import call
from test_wp4_portal_publication_database import PortalPublicationTests
import test_wp4_dispatch_database as foundation


class CommitFault:
    """Real connection, injected acknowledgement error; never a process crash."""
    def __init__(self, connection, after):
        object.__setattr__(self, 'connection', connection)
        object.__setattr__(self, 'after', after)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __setattr__(self, name, value):
        setattr(self.connection, name, value)

    def commit(self):
        if self.after:
            self.connection.commit()
        raise OSError('Synthetic commit acknowledgement loss')


@unittest.skipUnless(foundation.CONFIG is not None, 'Private isolated database input required')
class PublicationReadTests(PortalPublicationTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser_pool = iter(foundation.CONFIG['browser_sessions'])

    def store(self, kind='worker', factory=None):
        config = foundation.CONFIG[kind]
        return IsolatedPortalPublicationStore(factory or (lambda: psycopg.connect(**config)),
                                               foundation.CONFIG['database'], config['user'])

    def browser(self, fixture, expired=False):
        raw = next(self.browser_pool)
        # Digests already registered by the private host helper.
        offset = "interval '61 minutes'" if expired else "interval '1 minute'"
        self.admin.execute("WITH moment AS (SELECT clock_timestamp()-" + offset + " AS t) "
            "INSERT INTO retail.owner_portal_sessions SELECT %s,%s,%s,t,t+interval '1 hour',NULL FROM moment",
            (digest(raw), self.owner, digest(session_csrf(raw))))
        self.admin.commit()
        app = FastAPI()
        install_isolated_publication_reads(app, self.store('reader'), raw)
        headers = [(b'host', b'127.0.0.1:18081'), (b'cookie', ('raa_portal_session=' + raw).encode())]
        return app, headers, raw

    def path(self, action, export=False):
        return '/portal/v2/publications/' + action + ('/export' if export else '')

    def count(self):
        counts = self.admin.execute('SELECT (SELECT count(*) FROM retail.portal_publications_v2),'
                                   '(SELECT count(*) FROM retail.portal_publication_audit_v2)').fetchone()
        self.admin.rollback()
        return counts

    def test_reads_actual_reader_login_only_four_functions(self):
        with psycopg.connect(**foundation.CONFIG['reader']) as conn:
            self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0], 'on')
            self.assertEqual(conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='retail' AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')").fetchone()[0], 4)
            for table in ('portal_publications_v2', 'portal_publication_intents_v2', 'owner_portal_sessions', 'report_revisions'):
                self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE')",
                                               ('retail.' + table,)).fetchone()[0])
            for fn in ('api_accept_portal_publication_v2(uuid,text)', 'api_decide_portal_request_v2(text,text,uuid,text,text,text)',
                       'api_issue_portal_request_v3(uuid,text,text,uuid)', 'portal_owner_identity_v2(text)'):
                self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')", ('retail.'+fn,)).fetchone()[0])
        self.assertEqual(self.admin.execute("SELECT count(*) FROM pg_roles WHERE rolname='raa_wp4_portal_read_v2' AND NOT rolcanlogin").fetchone()[0], 1)
        self.admin.rollback()

    def test_reads_adapter_returns_only_after_commit_ten_replays(self):
        approved = self.decide_portal(self.fixture_portal())
        action, key = approved['action_id'], 'adapter-' + uuid4().hex
        store = self.store()
        receipt = store.accept(action, key)
        self.assertEqual(store.reconcile(action), receipt)
        for _ in range(10):
            self.assertEqual(store.accept(action, key), receipt)
        self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.portal_publications_v2 WHERE action_id=%s', (action,)).fetchone()[0], 1)
        self.admin.rollback()

    def test_reads_adapter_failed_commit_not_returned_and_rollback(self):
        approved = self.decide_portal(self.fixture_portal())
        store = self.store(factory=lambda: CommitFault(psycopg.connect(**foundation.CONFIG['worker']), False))
        before = self.count()
        with self.assertRaises(PortalOutcomeUncertain):
            store.accept(approved['action_id'], 'before-commit-' + uuid4().hex)
        self.assertEqual(self.count(), before)
        self.assertIsNone(self.store().reconcile(approved['action_id']))

    def test_reads_real_commit_simulated_lost_ack_then_reconcile_original_identity(self):
        approved = self.decide_portal(self.fixture_portal())
        action, key = approved['action_id'], 'lost-ack-' + uuid4().hex
        store = self.store(factory=lambda: CommitFault(psycopg.connect(**foundation.CONFIG['worker']), True))
        before = self.count()
        with self.assertRaises(PortalOutcomeUncertain):
            store.accept(action, key)
        actual = self.store()
        receipt = actual.reconcile(action)
        self.assertIsNotNone(receipt)
        self.assertEqual(actual.accept(action, key), receipt)
        self.assertEqual(self.count(), (before[0]+1, before[1]+1))
        with self.assertRaises(HTTPException) as conflict:
            actual.accept(action, 'different-key-' + uuid4().hex)
        self.assertEqual(conflict.exception.status_code, 409)

    def test_reads_exact_asgi_export_headers_and_repeated_read_no_mutation(self):
        f = self.fixture_portal()
        app, headers, raw = self.browser(f)
        approved = self.decide_portal(f)
        receipt = self.store().accept(approved['action_id'], 'export-' + uuid4().hex)
        before = self.count()
        status, body, reply = call(app, self.path(approved['action_id'], True), headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(body, foundation.CONFIG['base']['report'].encode('utf-8'))
        response_headers = dict(reply)
        self.assertEqual(response_headers[b'cache-control'], b'no-store')
        self.assertEqual(response_headers[b'x-content-type-options'], b'nosniff')
        self.assertEqual(response_headers[b'x-report-sha256'].decode(), sha256(body).hexdigest())
        self.assertEqual(response_headers[b'content-disposition'].decode(),
                         'attachment; filename="report-' + f['case'] + '-revision-1.json"')
        self.assertNotIn(raw.encode(), body)
        for _ in range(10):
            status, body, _ = call(app, self.path(approved['action_id']), headers=headers)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), receipt)
        self.assertEqual(self.count(), before)

    def test_reads_draft_and_approval_are_not_publication(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        path = '/portal/v2/requests/' + f['snapshot']['request']['proposal_id']
        status, body, _ = call(app, path, headers=headers)
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)['publication'])
        approved = self.decide_portal(f)
        for export in (False, True):
            status, body, _ = call(app, self.path(approved['action_id'], export), headers=headers)
            self.assertEqual(status, 404)
            self.assertNotIn(foundation.CONFIG['base']['report'].encode(), body)

    def test_reads_expired_unaccepted_denied_no_export(self):
        f = self.fixture_portal(seconds=1.2)
        approved = self.decide_portal(f)
        app, headers, _ = self.browser(f)
        self.wait_expired(f['snapshot']['request']['proposal_id'])
        with self.assertRaises(HTTPException) as expired:
            self.store().accept(approved['action_id'], 'expired-' + uuid4().hex)
        self.assertEqual(expired.exception.status_code, 409)
        self.assertEqual(call(app, self.path(approved['action_id'], True), headers=headers)[0], 404)

    def test_reads_uncommitted_asgi_invisible_then_committed_visible(self):
        f = self.fixture_portal()
        approved = self.decide_portal(f)
        app, headers, _ = self.browser(f)
        with self.connect('worker') as conn:
            self.accept_portal(approved, conn=conn)
            self.assertEqual(call(app, self.path(approved['action_id'], True), headers=headers)[0], 404)
            conn.commit()
            self.assertEqual(call(app, self.path(approved['action_id'], True), headers=headers)[0], 200)

    def test_reads_later_export_does_not_restart_original_deadline(self):
        f = self.fixture_portal(seconds=1.2)
        approved = self.decide_portal(f)
        app, headers, _ = self.browser(f)
        receipt = self.store().accept(approved['action_id'], 'late-export-' + uuid4().hex)
        self.wait_expired(f['snapshot']['request']['proposal_id'])
        status, body, _ = call(app, self.path(approved['action_id'], True), headers=headers)
        self.assertEqual((status, body), (200, foundation.CONFIG['base']['report'].encode()))
        self.assertEqual(self.store().reconcile(approved['action_id']), receipt)
        self.assertEqual(self.admin.execute('SELECT extract(epoch FROM expires_at-created_at) FROM '
            'retail.portal_approval_requests_v3 WHERE request_id=%s', (f['snapshot']['request']['proposal_id'],)).fetchone()[0], 86400)
        self.admin.rollback()

    def test_reads_expired_and_revoked_sessions_denied_direct_sql_and_asgi(self):
        f = self.fixture_portal()
        approved = self.decide_portal(f)
        self.store().accept(approved['action_id'], 'session-' + uuid4().hex)
        for expired in (True, False):
            app, headers, raw = self.browser(f, expired)
            if not expired:
                self.admin.execute('UPDATE retail.owner_portal_sessions SET revoked_at=clock_timestamp() WHERE session_sha256=%s', (digest(raw),))
                self.admin.commit()
            self.assertEqual(call(app, self.path(approved['action_id'], True), headers=headers)[0], 303)
            with self.assertRaises(HTTPException) as error:
                self.store('reader').publication(digest(raw), approved['action_id'], True)
            self.assertEqual(error.exception.status_code, 401)

    def test_reads_fixed_browser_boundary_denies_bearer_cross_origin_and_post(self):
        f = self.fixture_portal()
        approved = self.decide_portal(f)
        app, headers, _ = self.browser(f)
        path = self.path(approved['action_id'], True)
        before = self.count()
        self.assertEqual(call(app, path)[0], 303)
        for extra, status in (([(b'authorization', b'Bearer synthetic-service')], 400),
                              ([(b'origin', b'https://evil.invalid')], 403),
                              ([(b'sec-fetch-site', b'cross-site')], 403),
                              ([(b'host', b'127.0.0.1:18081')], 400),
                              ([(b'cookie', b'raa_portal_session=' + b'0'*64)], 400)):
            self.assertEqual(call(app, path, headers=headers+extra)[0], status)
        self.assertEqual(call(app, path, headers=headers, query=b'x=1')[0], 400)
        self.assertEqual(call(app, path, method='POST', headers=headers+[(b'origin', b'http://127.0.0.1:18081')])[0], 405)
        self.assertEqual(self.count(), before)

    def test_reads_publisher_and_service_cannot_export_or_substitute_owner_token(self):
        f = self.fixture_portal()
        approved = self.decide_portal(f)
        self.store().accept(approved['action_id'], 'rights-' + uuid4().hex)
        for kind in ('worker', 'issuer', 'reviewer'):
            with self.assertRaises(HTTPException) as denied:
                self.store(kind).publication(f['session'], approved['action_id'], True)
            self.assertEqual(denied.exception.status_code, 401)
        with self.assertRaises(HTTPException) as denied:
            self.store('reader').publication(foundation.CONFIG['owner_hash'], approved['action_id'], True)
        self.assertEqual(denied.exception.status_code, 401)

    def test_reads_deferred_real_database_commit_fault_leaves_no_published_response(self):
        approved = self.decide_portal(self.fixture_portal())
        before = self.count()
        self.admin.execute("CREATE FUNCTION pg_temp.fail_read_commit() RETURNS trigger LANGUAGE plpgsql AS $$ "
                           "BEGIN RAISE EXCEPTION 'Synthetic deferred fault'; END $$")
        self.admin.execute('CREATE CONSTRAINT TRIGGER portal_read_test_fault AFTER INSERT ON retail.portal_publications_v2 '
                           'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_read_commit()')
        self.admin.commit()
        try:
            with self.assertRaises(PortalOutcomeUncertain):
                self.store().accept(approved['action_id'], 'deferred-' + uuid4().hex)
            self.assertEqual(self.count(), before)
            self.assertIsNone(self.store().reconcile(approved['action_id']))
        finally:
            self.admin.execute('DROP TRIGGER portal_read_test_fault ON retail.portal_publications_v2')
            self.admin.commit()

    def test_reads_isolation_and_autocommit_and_login_mismatch_refused(self):
        config = foundation.CONFIG['worker']
        with self.assertRaises(ValueError):
            IsolatedPortalPublicationStore(lambda: None, 'raa_wp2_validation', config['user'])
        for factory in (lambda: psycopg.connect(**config, autocommit=True),
                        lambda: psycopg.connect(**foundation.CONFIG['reader'])):
            with self.assertRaises(HTTPException) as denied:
                self.store(factory=factory).reconcile(str(uuid4()))
            self.assertEqual(denied.exception.status_code, 503)

    def test_reads_invalid_canonical_paths_and_missing_objects(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        self.assertEqual(call(app, self.path('not-a-uuid'), headers=headers)[0], 422)
        self.assertEqual(call(app, self.path(str(uuid4())), headers=headers)[0], 404)
        self.assertEqual(call(app, '/portal/v2/requests/' + str(uuid4()), headers=headers)[0], 404)

    def test_reads_busy_and_release_slot_after_invalid_database_result(self):
        store = self.store('reader')
        store.slot.acquire()
        try:
            with self.assertRaises(HTTPException) as busy:
                store.identity('0'*64)
            self.assertEqual(busy.exception.status_code, 429)
        finally:
            store.slot.release()
        with self.assertRaises(HTTPException):
            store.publication('0'*64, str(uuid4()), True)
        self.assertTrue(store.slot.acquire(blocking=False))
        store.slot.release()

    def test_reads_receipt_validation_rejects_tampered_projection(self):
        f = self.fixture_portal()
        approved = self.decide_portal(f)
        accepted = self.accept_portal(approved)
        action = approved['action_id']
        self.assertIsNotNone(self.store().receipt(accepted, action))
        for field, changed in (('contract_version', 'old-contract'), ('report_revision', 2),
                               ('report_payload_sha256', '0'*64), ('publication_semantics', 'physical-file')):
            bad = json.loads(json.dumps(accepted))
            bad['request'][field] = changed
            with self.assertRaises(HTTPException) as invalid:
                self.store().receipt(bad, action)
            self.assertEqual(invalid.exception.status_code, 503)
        for name, changed in (('accepted_at', accepted['request']['expires_at']), ('target_id', 'old-target')):
            bad = json.loads(json.dumps(accepted))
            bad['publication'][name] = changed
            with self.assertRaises(HTTPException):
                self.store().receipt(bad, action)
        # Pure projection tamper cases above do not mutate persisted SQL facts.

    def test_reads_zz_owner_revocation_denies_committed_export_and_reconciliation(self):
        f = self.fixture_portal()
        approved = self.decide_portal(f)
        app, headers, _ = self.browser(f)
        self.store().accept(approved['action_id'], 'owner-revoke-' + uuid4().hex)
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s', (self.owner,))
        self.admin.commit()
        self.assertEqual(call(app, self.path(approved['action_id'], True), headers=headers)[0], 303)
        for store, method, args in ((self.store('reader'), 'publication', (f['session'], approved['action_id'], True)),
                                    (self.store(), 'reconcile', (approved['action_id'],))):
            with self.assertRaises(HTTPException) as denied:
                getattr(store, method)(*args)
            self.assertEqual(denied.exception.status_code, 401)


if __name__ == '__main__':
    foundation.CONFIG = json.loads(sys.stdin.read())
    PublicationReadTests.__unittest_skip__ = False
    names = [name for name in dir(PublicationReadTests) if name.startswith('test_reads_')]
    suite = unittest.TestSuite(PublicationReadTests(name) for name in names)

    class PrivateResult(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.error_types, self.sqlstates, self.constraints = [], [], []

        def addError(self, test, error):
            self.error_types.append(error[0].__name__)
            self.sqlstates.append(getattr(error[1], 'sqlstate', None) or 'none')
            name = getattr(getattr(error[1], 'diag', None), 'constraint_name', None)
            self.constraints.append(name if isinstance(name, str) and re.fullmatch(r'[a-z0-9_]{1,128}', name) else 'none')
            super().addError(test, error)

    result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=PrivateResult).run(suite)
    print(json.dumps({'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
        'failed_tests': [getattr(t, '_testMethodName', 'class_setup') for t, _ in result.errors+result.failures],
        'error_types': result.error_types, 'sqlstates': result.sqlstates, 'constraints': result.constraints}))
