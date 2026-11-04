"""Pure coordinator/store contracts. Mock evidence, not SQL/NTFS integration."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import unittest
from unittest.mock import Mock
from uuid import uuid4

from api.local_publication import AuthorizationDenied, PublicationBusy, TargetConflict, UnsafeTarget
from api.publication_dispatch import (
    DispatchBindingError, DispatchUncertain, IsolatedPublicationDispatcher,
    IsolatedPublicationStore,
)


class AdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.action = str(uuid4()); self.case = str(uuid4()); self.lease = str(uuid4())
        self.body = '{"synthetic":"\u041f"}'.encode()
        self.claim = {'action_id': self.action, 'case_id': self.case, 'lease_id': self.lease,
            'mode': 'write', 'lease_active': True, 'state': 'in_progress', 'revision': 1,
            'target_id': 'local-approved-report-json-v1',
            'relative_path': f'reports/approved/v1/{self.case}/revision-1.json',
            'content_text': self.body.decode(), 'content_sha256': sha256(self.body).hexdigest(),
            'content_bytes': len(self.body), 'sequence': 3, 'write_attempts': 1}
        self.tx = Mock(); self.tx.claim.side_effect = lambda *args: deepcopy(self.claim)
        self.tx.state.side_effect = lambda *args: deepcopy(self.claim)
        self.tx.authorize.return_value = True
        self.tx.observe.return_value = dict(self.claim, state='succeeded', sequence=4)
        self.active = 0; self.transactions = 0
        outer = self
        class Store:
            @contextmanager
            def transaction(self):
                outer.active += 1; outer.transactions += 1
                try: yield outer.tx
                finally: outer.active -= 1
        self.files = Mock(); self.files.publish.return_value = 'created'
        self.dispatcher = IsolatedPublicationDispatcher(Store(), self.files)

    def step(self, mode='write', checkpoint=None):
        return self.dispatcher.step(self.action, mode, 'fixed-claim-123', checkpoint)

    def test_two_transactions_and_held_fresh_checks_exact_utf8(self):
        def publish(case, content, digest, authorize, checkpoint=None):
            self.assertEqual((self.active, self.transactions), (1, 2))
            self.assertEqual((case, content, digest), (self.case, self.body, sha256(self.body).hexdigest()))
            self.assertTrue(authorize()); self.assertTrue(authorize())
            return 'created'
        self.files.publish.side_effect = publish
        result = self.step()
        self.assertEqual((self.active, self.transactions, result['state']), (0, 2, 'succeeded'))
        self.assertEqual(self.tx.authorize.call_count, 3)
        self.tx.observe.assert_called_once_with(self.action, self.lease, 'matching', sha256(self.body).hexdigest(), len(self.body))
        self.assertNotIn('content_text', result); self.assertFalse(result['dispatch_enabled'])

    def test_invalid_caller_inputs_never_open_db(self):
        for action, mode, key in ((self.action.upper(), 'write', 'fixed-key'),
                (self.action, 'arbitrary', 'fixed-key'), (self.action, 'write', 'short'),
                (self.action, 'write', 'x'*129), (self.action, 'write', 'bad key!'),
                (None, 'reconcile', 'fixed-key')):
            with self.assertRaises(DispatchBindingError): self.dispatcher.step(action, mode, key)
        self.assertEqual(self.transactions, 0); self.files.publish.assert_not_called()

    def test_tampered_binding_never_touches_files(self):
        original = deepcopy(self.claim)
        for key, value in (('revision', True), ('relative_path', '../outside'),
                ('target_id', 'other'), ('content_text', 'changed'), ('content_bytes', True),
                ('content_sha256', '0'*64), ('case_id', self.case.upper()), ('lease_id', None),
                ('content_text', '\ud800'), ('content_bytes', 131073), ('mode', 'reconcile')):
            self.claim = dict(original, **{key: value})
            with self.subTest(field=key):
                with self.assertRaises(DispatchBindingError): self.step()
        self.files.publish.assert_not_called(); self.files.reconcile.assert_not_called()

    def test_stale_claim_without_content_never_touches_files(self):
        self.claim['lease_active'] = False; del self.claim['content_text']
        result = self.step()
        self.assertIsNone(result['observation']); self.assertEqual(self.transactions, 1)
        self.files.publish.assert_not_called()

    def test_newer_lease_or_changed_binding_denied_under_lock(self):
        for key, value in (('lease_id', str(uuid4())), ('lease_active', False),
                ('case_id', str(uuid4())), ('state', 'succeeded'), ('content_bytes', 1)):
            self.tx.state.return_value = None
            self.tx.state.side_effect = lambda *args: dict(self.claim, **{key: value})
            with self.assertRaises(DispatchBindingError): self.step()
        self.files.publish.assert_not_called()

    def test_reconcile_never_uses_write_permission(self):
        self.claim['mode'] = 'reconcile'; self.tx.authorize.return_value = False
        self.files.reconcile.return_value = 'missing'
        self.step('reconcile')
        self.tx.observe.assert_called_once_with(self.action, self.lease, 'missing', None, None)
        self.files.publish.assert_not_called()

    def test_denied_write_and_transient_errors_are_unknown(self):
        self.tx.authorize.return_value = False
        self.step()
        self.files.publish.assert_not_called()
        self.tx.observe.assert_called_with(self.action, self.lease, 'unknown', None, None)
        self.tx.authorize.return_value = True
        for error in (AuthorizationDenied, PublicationBusy):
            self.files.publish.side_effect = error('Synthetic failure')
            self.step()
            self.tx.observe.assert_called_with(self.action, self.lease, 'unknown', None, None)

    def test_collision_or_unsafe_target_are_ambiguous(self):
        for error in (TargetConflict, UnsafeTarget):
            self.files.publish.side_effect = error('Synthetic failure')
            self.step()
            self.tx.observe.assert_called_with(self.action, self.lease, 'ambiguous', None, None)

    def test_unrecognized_file_outcome_is_never_success(self):
        self.files.publish.return_value = 'maybe'
        self.step(); self.tx.observe.assert_called_with(self.action, self.lease, 'unknown', None, None)
        self.claim['mode'] = 'reconcile'; self.files.reconcile.return_value = 'maybe'
        self.step('reconcile'); self.tx.observe.assert_called_with(self.action, self.lease, 'unknown', None, None)

    def test_checkpoint_order_and_no_receipt_after_abort(self):
        checkpoints = []
        self.step(checkpoint=checkpoints.append)
        self.assertEqual(checkpoints, ['claim_committed', 'receipt_pending', 'receipt_committed'])
        self.tx.observe.reset_mock()
        def abort(point):
            if point == 'claim_committed': raise SystemExit(77)
        with self.assertRaises(SystemExit): self.step(checkpoint=abort)
        self.tx.observe.assert_not_called()

    def test_store_main_refused_and_identity_mismatch_closes_without_write(self):
        factory = Mock()
        for name in ('raa_wp2_validation', 'postgres', 'raa_wp4_dispatch_test_bad'):
            with self.assertRaises(DispatchBindingError): IsolatedPublicationStore(factory, name)
        factory.assert_not_called()
        conn = Mock(); conn.autocommit = False
        conn.execute.return_value.fetchone.return_value = ('raa_wp2_validation',)
        factory.return_value = conn
        store = IsolatedPublicationStore(factory, 'raa_wp4_dispatch_test_0123456789ab')
        with self.assertRaises(DispatchBindingError):
            with store.transaction(): self.fail('Wrong DB admitted')
        conn.commit.assert_not_called(); conn.rollback.assert_called_once(); conn.close.assert_called_once()
        conn.execute.assert_called_once_with('SELECT current_database()')

    def test_store_commit_error_sanitized_and_rolled_back_and_closed(self):
        conn = Mock(); conn.autocommit = False
        conn.execute.return_value.fetchone.return_value = ('raa_wp4_dispatch_test_0123456789ab',)
        conn.commit.side_effect = RuntimeError('postgresql://private-password-and-report')
        store = IsolatedPublicationStore(lambda: conn, 'raa_wp4_dispatch_test_0123456789ab')
        with self.assertRaises(DispatchUncertain) as error:
            with store.transaction(): pass
        self.assertNotIn('private-password', str(error.exception)); self.assertTrue(error.exception.__suppress_context__)
        self.assertEqual(conn.rollback.call_count, 2); conn.close.assert_called_once()

    def test_store_autocommit_refused_before_any_sql(self):
        conn = Mock(); conn.autocommit = True
        store = IsolatedPublicationStore(lambda: conn, 'raa_wp4_dispatch_test_0123456789ab')
        with self.assertRaises(DispatchBindingError):
            with store.transaction(): self.fail('Autocommit loses locks')
        conn.execute.assert_not_called(); conn.commit.assert_not_called(); conn.close.assert_called_once()


if __name__ == '__main__': unittest.main()
