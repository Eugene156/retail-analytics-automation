"""Private real-PostgreSQL new-target tests; no NTFS, HTTP or real owner action."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import io
import json
import re
import sys
import threading
import time
import unittest
from uuid import uuid4

import psycopg
import test_wp4_dispatch_database as foundation


@unittest.skipUnless(foundation.CONFIG is not None, 'Private isolated database input required')
class PortalPublicationTests(foundation.DispatchDatabaseTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Test-connection-only: don't emit failing-row secret digests to logs.
        # No cluster/database/runtime logging setting is changed.
        cls.admin.execute("SET log_error_verbosity=terse")
        cls.admin.execute("SET log_parameter_max_length_on_error=0")
        cls.sessions = iter(foundation.CONFIG['sessions'])
        cls.admin.execute("INSERT INTO retail.portal_publication_policies_v2 VALUES('owner-portal-acceptance-v2',%s,86400)",
                          (cls.owner,))
        cls.admin.commit()

    def tearDown(self):
        self.admin.rollback()

    def connect(self, kind):
        conn = psycopg.connect(**foundation.CONFIG[kind])
        conn.read_only = False
        self.assertEqual(conn.execute('SELECT current_database()').fetchone()[0], foundation.CONFIG['database'])
        return conn

    def fixture_portal(self, seconds=None):
        case = uuid4()
        report = foundation.CONFIG['base']['report']
        digest = sha256(report.encode()).hexdigest()
        session, csrf = next(self.sessions)
        self.admin.execute("INSERT INTO retail.report_cases(case_id,idempotency_key,request_identity) VALUES(%s,%s,%s::jsonb)",
                           (case, 'portal-case-' + case.hex, json.dumps(foundation.CONFIG['base']['request'])))
        self.admin.execute("INSERT INTO retail.report_audit_events(case_id,event_type) VALUES(%s,'request_received')", (case,))
        self.admin.execute("INSERT INTO retail.report_revisions(case_id,revision,schema_version,payload_text,payload_sha256) "
                           "VALUES(%s,1,'deterministic-comparison-report-v1',%s,%s)", (case, report, digest))
        self.admin.execute("UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1 WHERE case_id=%s", (case,))
        self.admin.execute("INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES(%s,'revision_created',1)", (case,))
        self.admin.execute("WITH moment AS (SELECT clock_timestamp() AS t) INSERT INTO retail.owner_portal_sessions "
                           "SELECT %s,%s,%s,t-interval '1 minute',t+interval '59 minutes',NULL FROM moment",
                           (session, self.owner, csrf))
        if seconds is None:
            self.admin.commit()
            with self.connect('issuer') as conn:
                snapshot = json.loads(conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,NULL)',
                                     (case, digest, 'portal-request-' + uuid4().hex)).fetchone()[0])
        else:
            # Privileged synthetic backdating only; original TTL stays 86400.
            request, key = uuid4(), 'short-request-' + uuid4().hex
            snapshot = self.admin.execute("WITH times AS (SELECT clock_timestamp()-interval '86400 seconds' "
                "+ %s*interval '1 second' AS c), body AS (SELECT c,retail.portal_request_payload_v3(%s,%s,%s,%s,%s,c,"
                "c+interval '86400 seconds',1,%s,NULL,NULL) AS b FROM times), inserted AS ("
                "INSERT INTO retail.portal_approval_requests_v3 SELECT %s,%s,1,%s,'owner-portal-acceptance-v2',1,%s,"
                "NULL,NULL,c,c+interval '86400 seconds',%s,%s,b,encode(sha256(convert_to(b,'UTF8')),'hex') FROM body "
                "RETURNING request_id,created_at) INSERT INTO retail.portal_publication_audit_v2(subject_id,kind,occurred_at) "
                "SELECT request_id,'request_created',created_at FROM inserted",
                (seconds, request, case, digest, len(report.encode()), self.owner, key, request, case, self.owner, key,
                 digest, len(report.encode())))
            snapshot = json.loads(self.admin.execute('SELECT retail.portal_request_snapshot_v3(%s)', (request,)).fetchone()[0])
            self.admin.commit()
        return dict(snapshot=snapshot, case=str(case), session=session, csrf=csrf)

    def decide_portal(self, f, choice='approve', key=None, conn=None):
        args = (f['session'], f['csrf'], f['snapshot']['request']['proposal_id'],
                f['snapshot']['request_sha256'], choice, key or 'portal-decision-' + uuid4().hex)
        if conn is not None:
            return json.loads(conn.execute('SELECT retail.api_decide_portal_request_v2(%s,%s,%s,%s,%s,%s)', args).fetchone()[0])
        with self.connect('reviewer') as connection:
            return json.loads(connection.execute('SELECT retail.api_decide_portal_request_v2(%s,%s,%s,%s,%s,%s)', args).fetchone()[0])

    def accept_portal(self, snapshot, key=None, conn=None):
        args = (snapshot['action_id'], key or 'portal-accept-' + uuid4().hex)
        if conn is not None:
            return json.loads(conn.execute('SELECT retail.api_accept_portal_publication_v2(%s,%s)', args).fetchone()[0])
        with self.connect('worker') as connection:
            return json.loads(connection.execute('SELECT retail.api_accept_portal_publication_v2(%s,%s)', args).fetchone()[0])

    def wait_expired(self, request):
        remaining = self.admin.execute("SELECT greatest(0,extract(epoch FROM expires_at-clock_timestamp())) "
                                      "FROM retail.portal_approval_requests_v3 WHERE request_id=%s", (request,)).fetchone()[0]
        self.admin.rollback()
        time.sleep(float(remaining) + 0.08)

    def test_portal_actual_login_scoped_roles_and_no_tables(self):
        for kind, permitted in (('issuer', 'api_issue_portal_request_v3(uuid,text,text,uuid)'),
                                ('reviewer', 'api_decide_portal_request_v2(text,text,uuid,text,text,text)'),
                                ('worker', 'api_accept_portal_publication_v2(uuid,text)')):
            with psycopg.connect(**foundation.CONFIG[kind]) as conn:
                self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0], 'on')
                self.assertTrue(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')", ('retail.' + permitted,)).fetchone()[0])
                self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,'retail.portal_publications_v2','SELECT,INSERT,UPDATE')").fetchone()[0])
                if kind != 'reviewer':
                    self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,'retail.api_decide_portal_request_v2(text,text,uuid,text,text,text)','EXECUTE')").fetchone()[0])
                if kind != 'worker':
                    self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,'retail.api_accept_portal_publication_v2(uuid,text)','EXECUTE')").fetchone()[0])
        self.assertEqual(self.admin.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('raa_wp4_portal_issue_v3',"
            "'raa_wp4_portal_review_v2','raa_wp4_portal_publish_v2') AND NOT rolcanlogin").fetchone()[0], 3)
        self.admin.rollback()

    def test_portal_new_target_exact_bytes_ten_replays(self):
        f = self.fixture_portal()
        request = f['snapshot']['request']
        self.assertEqual(request['contract_version'], 'owner-portal-approval-request-v3')
        self.assertEqual(request['action']['target']['target_id'], 'local-owner-portal-report-v2')
        self.assertNotIn('relative_path', request['action']['target'])
        approved = self.decide_portal(f)
        self.assertIsNone(approved['publication'])
        key = 'ten-replays-' + uuid4().hex
        accepted = self.accept_portal(approved, key)
        for _ in range(10):
            self.assertEqual(self.accept_portal(approved, key), accepted)
        body, digest, size = self.admin.execute('SELECT content_text,content_sha256,content_bytes '
            'FROM retail.portal_publication_intents_v2 WHERE action_id=%s', (approved['action_id'],)).fetchone()
        self.assertEqual((body, digest, size), (foundation.CONFIG['base']['report'], sha256(body.encode()).hexdigest(), len(body.encode())))
        self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.portal_publications_v2 WHERE action_id=%s', (approved['action_id'],)).fetchone()[0], 1)
        self.admin.rollback()
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            self.accept_portal(approved, 'changed-key-' + uuid4().hex)

    def test_portal_pause_before_acceptance_denies_expired_request(self):
        f = self.fixture_portal(seconds=1.2)
        approved = self.decide_portal(f)
        with self.connect('worker') as conn:
            # Transaction began before expiry; transaction_timestamp is stale.
            self.wait_expired(f['snapshot']['request']['proposal_id'])
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                self.accept_portal(approved, conn=conn)
            conn.rollback()
        self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.portal_publications_v2 WHERE action_id=%s', (approved['action_id'],)).fetchone()[0], 0)
        self.admin.rollback()

    def test_portal_pause_after_acceptance_delayed_commit_is_logical_success_only(self):
        f = self.fixture_portal(seconds=1.2)
        approved = self.decide_portal(f)
        conn = self.connect('worker')
        try:
            accepted = self.accept_portal(approved, conn=conn)
            with self.connect('worker') as reader:
                invisible = json.loads(reader.execute('SELECT retail.api_portal_publication_state_v2(%s)', (approved['action_id'],)).fetchone()[0])
                self.assertIsNone(invisible['publication'])
            self.wait_expired(f['snapshot']['request']['proposal_id'])
            with self.connect('issuer') as issuer:
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    issuer.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                        (f['case'], f['snapshot']['request']['report_payload_sha256'], 'racing-renewal-' + uuid4().hex,
                         f['snapshot']['request']['proposal_id']))
                issuer.rollback()
            conn.commit()
            on_time = self.admin.execute('SELECT p.accepted_at<r.expires_at AND clock_timestamp()>=r.expires_at '
                'FROM retail.portal_publications_v2 p JOIN retail.portal_publication_intents_v2 a USING(action_id) '
                'JOIN retail.portal_approval_requests_v3 r USING(request_id) WHERE p.action_id=%s', (approved['action_id'],)).fetchone()[0]
            self.assertTrue(on_time)
            self.admin.rollback()
            with self.connect('worker') as reader:
                visible = json.loads(reader.execute('SELECT retail.api_portal_publication_state_v2(%s)', (approved['action_id'],)).fetchone()[0])
                self.assertEqual(visible['publication'], accepted['publication'])
        finally:
            conn.rollback(); conn.close()

    def test_portal_rollback_after_acceptance_leaves_no_publication_or_audit(self):
        approved = self.decide_portal(self.fixture_portal())
        with self.connect('worker') as conn:
            result = self.accept_portal(approved, conn=conn)
            conn.rollback()
        self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.portal_publication_audit_v2 WHERE subject_id=%s',
            (result['publication']['publication_id'],)).fetchone()[0], 0)
        self.admin.rollback()
        self.assertIsNotNone(self.accept_portal(approved)['publication'])

    def test_portal_actual_audit_fault_rolls_back_effect(self):
        approved = self.decide_portal(self.fixture_portal())
        self.admin.execute("CREATE FUNCTION pg_temp.fail_portal_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                           "IF NEW.kind='publication_accepted' THEN RAISE EXCEPTION 'Synthetic audit failure'; END IF; RETURN NEW; END $$")
        self.admin.execute('CREATE TRIGGER portal_test_fault AFTER INSERT ON retail.portal_publication_audit_v2 '
                           'FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_portal_audit()')
        self.admin.commit()
        try:
            with self.assertRaises(psycopg.errors.RaiseException):
                self.accept_portal(approved)
            self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.portal_publications_v2 WHERE action_id=%s', (approved['action_id'],)).fetchone()[0], 0)
            self.admin.rollback()
        finally:
            self.admin.execute('DROP TRIGGER portal_test_fault ON retail.portal_publication_audit_v2'); self.admin.commit()
        self.assertIsNotNone(self.accept_portal(approved)['publication'])

    def test_portal_concurrent_same_key_acceptance_single_event(self):
        approved = self.decide_portal(self.fixture_portal())
        key, barrier = 'same-key-' + uuid4().hex, threading.Barrier(2)
        def run():
            with self.connect('worker') as conn:
                barrier.wait(timeout=5)
                try:
                    return self.accept_portal(approved, key, conn=conn)
                except psycopg.errors.LockNotAvailable:
                    conn.rollback(); return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        final = self.accept_portal(approved, key)
        self.assertTrue(any(r is not None for r in results))
        for result in results:
            if result is not None: self.assertEqual(result, final)
        self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.portal_publications_v2 WHERE action_id=%s', (approved['action_id'],)).fetchone()[0], 1)
        self.admin.rollback()

    def test_portal_expired_approved_successor_needs_fresh_decision_old_denied(self):
        f = self.fixture_portal(seconds=1.2)
        old = self.decide_portal(f)
        request = f['snapshot']['request']
        self.wait_expired(request['proposal_id'])
        key = 'successor-' + uuid4().hex
        with self.connect('issuer') as issuer:
            successor = json.loads(issuer.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                (f['case'], request['report_payload_sha256'], key, request['proposal_id'])).fetchone()[0])
        self.assertIsNone(successor['decision']); self.assertIsNone(successor['action_id'])
        self.assertEqual(successor['request']['generation'], 2)
        self.assertNotEqual(successor['request_sha256'], f['snapshot']['request_sha256'])
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept_portal(old)
        f['snapshot'] = successor
        approved = self.decide_portal(f)
        self.assertNotEqual(old['action_id'], approved['action_id'])
        self.assertIsNotNone(self.accept_portal(approved)['publication'])
        self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.portal_review_decisions_v2 d '
            'JOIN retail.portal_approval_requests_v3 r USING(request_id) WHERE r.case_id=%s', (f['case'],)).fetchone()[0], 2)
        self.admin.rollback()

    def test_portal_rejection_no_intent_early_renewal_denied(self):
        f = self.fixture_portal()
        rejected = self.decide_portal(f, 'reject')
        self.assertIsNone(rejected['action_id'])
        with self.connect('issuer') as issuer:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                issuer.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                    (f['case'], f['snapshot']['request']['report_payload_sha256'], 'early-renewal-' + uuid4().hex,
                     f['snapshot']['request']['proposal_id']))
            issuer.rollback()

    def test_portal_wrong_csrf_request_hash_and_expired_decision_denied(self):
        f = self.fixture_portal()
        for field in ('csrf', 'request_sha256'):
            bad = dict(f, snapshot=dict(f['snapshot']))
            if field == 'csrf': bad['csrf'] = '0' * 64
            else: bad['snapshot'][field] = '0' * 64
            with self.assertRaises(psycopg.Error): self.decide_portal(bad)
        expired = self.fixture_portal(seconds=0)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.decide_portal(expired)

    def test_portal_legacy_approval_is_not_retargeted(self):
        legacy = self.fixture()
        case = self.admin.execute('SELECT case_id FROM retail.publication_outbox_v1 WHERE action_id=%s', (legacy['action_id'],)).fetchone()[0]
        self.admin.rollback()
        with self.connect('issuer') as conn:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,NULL)',
                    (case, legacy['content_sha256'], 'no-convert-' + uuid4().hex))
            conn.rollback()

    def test_portal_immutable_rows_and_deferred_audit_bundle(self):
        f = self.fixture_portal()
        approved = self.decide_portal(f)
        accepted = self.accept_portal(approved)
        with self.assertRaises(psycopg.errors.RaiseException):
            self.admin.execute("UPDATE retail.portal_publications_v2 SET accepted_at=clock_timestamp() WHERE action_id=%s", (approved['action_id'],))
        self.admin.rollback()
        body = self.fixture_portal()  # complete fixture committed independently
        # An AFTER INSERT fault test above proves rollback; this verifies bundle
        # completeness by a synthetic decision without its event/intent.
        with self.assertRaises(psycopg.errors.RaiseException):
            self.admin.execute("INSERT INTO retail.portal_review_decisions_v2 VALUES(%s,%s,%s,%s,'approved',clock_timestamp())",
                (uuid4(), body['snapshot']['request']['proposal_id'], body['session'], 'missing-bundle-' + uuid4().hex))
            self.admin.commit()
        self.admin.rollback()
        self.assertIsNotNone(accepted['publication'])

    def test_portal_exact_sql_deadline_equality_and_invalid_samples(self):
        # Exercise the exact predicate used at the guarded acceptance point;
        # actual timed tests exercise the server's fresh clock separately.
        row = self.admin.execute("SELECT "
            "retail.portal_acceptance_in_window_v2(c,d,d-interval '1 microsecond'),"
            "retail.portal_acceptance_in_window_v2(c,d,d),"
            "retail.portal_acceptance_in_window_v2(c,d,d+interval '1 microsecond'),"
            "retail.portal_acceptance_in_window_v2(c,d,c-interval '1 microsecond'),"
            "retail.portal_acceptance_in_window_v2(c,d,NULL),"
            "retail.portal_acceptance_in_window_v2(c,d+interval '1 second',c) "
            "FROM (SELECT timestamptz '2026-10-05 UTC' c,timestamptz '2026-10-06 UTC' d) t").fetchone()
        self.assertEqual(row, (True, False, False, False, False, False))
        self.admin.rollback()

    def test_portal_ten_decision_replays_and_conflicting_choice_denied(self):
        f = self.fixture_portal()
        key = 'decision-replay-' + uuid4().hex
        approved = self.decide_portal(f, key=key)
        for _ in range(10):
            self.assertEqual(self.decide_portal(f, key=key), approved)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            self.decide_portal(f, 'reject', key)

    def test_portal_expired_rejection_stays_terminal(self):
        f = self.fixture_portal(seconds=1.2)
        self.decide_portal(f, 'reject')
        self.wait_expired(f['snapshot']['request']['proposal_id'])
        with self.connect('issuer') as conn:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                    (f['case'], f['snapshot']['request']['report_payload_sha256'], 'rejected-renewal-' + uuid4().hex,
                     f['snapshot']['request']['proposal_id']))
            conn.rollback()

    def test_portal_concurrent_successors_single_generation_fresh_86400(self):
        f = self.fixture_portal(seconds=0)
        request, barrier = f['snapshot']['request'], threading.Barrier(2)
        def run(_):
            with self.connect('issuer') as conn:
                barrier.wait(timeout=5)
                try:
                    return json.loads(conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                        (f['case'], request['report_payload_sha256'], 'concurrent-renewal-' + uuid4().hex,
                         request['proposal_id'])).fetchone()[0])
                except (psycopg.errors.LockNotAvailable, psycopg.errors.ObjectNotInPrerequisiteState):
                    conn.rollback(); return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.admin.execute('SELECT count(*),bool_and(extract(epoch FROM expires_at-created_at)=86400) '
            'FROM retail.portal_approval_requests_v3 WHERE predecessor_id=%s', (request['proposal_id'],)).fetchone(), (1, True))
        self.admin.rollback()

    def test_portal_raw_timestamp_override_is_ignored_and_audit_is_exact(self):
        f = self.fixture_portal()
        approved = self.decide_portal(f)
        pub_id = uuid4()
        accepted = self.admin.execute("INSERT INTO retail.portal_publications_v2 VALUES(%s,%s,%s,1,"
            "'local-owner-portal-report-v2',%s,timestamptz '2000-01-01 UTC') RETURNING accepted_at",
            (pub_id, approved['action_id'], f['case'], 'admin-fixture-' + uuid4().hex)).fetchone()[0]
        self.assertGreater(accepted.year, 2000)
        self.admin.execute("INSERT INTO retail.portal_publication_audit_v2(subject_id,kind,occurred_at) "
            "VALUES(%s,'publication_accepted',%s)", (pub_id, accepted))
        self.admin.commit()

    def test_portal_zz_revoked_owner_denies_acceptance_and_state(self):
        approved = self.decide_portal(self.fixture_portal())
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s', (self.owner,))
        self.admin.commit()
        with self.assertRaises(psycopg.errors.InsufficientPrivilege): self.accept_portal(approved)
        with self.connect('worker') as conn:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('SELECT retail.api_portal_publication_state_v2(%s)', (approved['action_id'],))
            conn.rollback()


if __name__ == '__main__':
    foundation.CONFIG = json.loads(sys.stdin.read())
    PortalPublicationTests.__unittest_skip__ = False
    names = [name for name in dir(PortalPublicationTests) if name.startswith('test_portal_')]
    suite = unittest.TestSuite(PortalPublicationTests(name) for name in names)
    class PrivateResult(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); self.error_types = []; self.sqlstates = []; self.constraints = []
        def addError(self, test, error):
            self.error_types.append(error[0].__name__)
            self.sqlstates.append(getattr(error[1], 'sqlstate', None) or 'none')
            name = getattr(getattr(error[1], 'diag', None), 'constraint_name', None)
            self.constraints.append(name if isinstance(name, str) and re.fullmatch(r'[a-z0-9_]{1,128}', name) else 'none')
            super().addError(test, error)
    result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=PrivateResult).run(suite)
    print(json.dumps({'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
        'failed_tests': [getattr(t, '_testMethodName', 'class_setup') for t, _ in result.errors + result.failures],
        'error_types': result.error_types, 'sqlstates': result.sqlstates, 'constraints': result.constraints}))
