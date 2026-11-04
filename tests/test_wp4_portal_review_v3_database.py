"""Private actual-login/SQL/ASGI new-target forms, not browser or main activation."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import io
import json
import re
import sys
import threading
import unittest
from urllib.parse import urlencode
from uuid import uuid4

import psycopg
from fastapi import FastAPI
from api.portal_review_v3 import IsolatedOwnerReview, install_isolated_review_v3
from test_wp4_portal_publication_reads_database import PublicationReadTests, CommitFault
from test_wp4_portal import call
import test_wp4_dispatch_database as foundation


@unittest.skipUnless(foundation.CONFIG is not None, 'Private isolated database input required')
class ReviewV3Tests(PublicationReadTests):
    def review_store(self):
        return IsolatedOwnerReview(self.store('reader'), self.store('reviewer'), self.store('issuer'))

    def app(self, review=None):
        app = FastAPI()
        install_isolated_review_v3(app, review or self.review_store(), foundation.CONFIG['portal_key'], foundation.CONFIG['service_token'])
        return app

    def browser(self, fixture, expired=False):
        _, headers, raw = super().browser(fixture, expired)
        return self.app(), headers, raw

    def detail(self, f):
        return '/portal/cases/' + f['case'] + '/requests/' + f['snapshot']['request']['proposal_id']

    def form(self, app, f, headers):
        status, body, _ = call(app, self.detail(f), headers=headers)
        self.assertEqual(status, 200)
        fields = dict((name.decode(), value.decode()) for name, value in
                      re.findall(rb'<input type="hidden" name="([a-z0-9_]+)" value="([a-zA-Z0-9_-]+)">', body))
        self.assertEqual(set(fields), {'csrf', 'revision', 'report_sha256', 'proposal_sha256', 'decision_key'})
        return dict(fields, confirm='yes', choice='approve')

    def post(self, app, f, headers, form):
        return call(app, self.detail(f)+'/decision', method='POST', body=urlencode(form).encode(),
                    headers=headers+[(b'origin', b'http://127.0.0.1:18081'), (b'content-type', b'application/x-www-form-urlencoded')])

    def issue(self, app, case, payload, key=None, headers=None, body=None):
        headers = headers if headers is not None else [(b'host', b'127.0.0.1:18081'),
            (b'authorization', ('Bearer '+foundation.CONFIG['service_token']).encode()),
            (b'content-type', b'application/json'), (b'idempotency-key', (key or 'issue-'+uuid4().hex).encode())]
        return call(app, '/api/v3/cases/'+case+'/approval-requests', method='POST',
                    body=body if body is not None else json.dumps(payload).encode(), headers=headers)

    def bare_case(self):
        case = str(uuid4())
        report = foundation.CONFIG['base']['report']
        self.admin.execute('INSERT INTO retail.report_cases(case_id,idempotency_key,request_identity) VALUES(%s,%s,%s::jsonb)',
            (case, 'forms-'+uuid4().hex, json.dumps(foundation.CONFIG['base']['request'])))
        self.admin.execute("INSERT INTO retail.report_audit_events(case_id,event_type) VALUES(%s,'request_received')", (case,))
        self.admin.execute("INSERT INTO retail.report_revisions(case_id,revision,schema_version,payload_text,payload_sha256) "
            "VALUES(%s,1,'deterministic-comparison-report-v1',%s,%s)", (case, report, sha256(report.encode()).hexdigest()))
        self.admin.execute("UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1 WHERE case_id=%s", (case,))
        self.admin.execute("INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES(%s,'revision_created',1)", (case,))
        self.admin.commit()
        return case, {'report_revision': 1, 'report_payload_sha256': sha256(report.encode()).hexdigest(), 'predecessor_request_id': None}

    def bundle_count(self, request):
        row = self.admin.execute('SELECT (SELECT count(*) FROM retail.portal_review_decisions_v2 WHERE request_id=%s),'
            '(SELECT count(*) FROM retail.portal_publication_intents_v2 WHERE request_id=%s),'
            '(SELECT count(*) FROM retail.portal_publications_v2 p JOIN retail.portal_publication_intents_v2 a USING(action_id) WHERE a.request_id=%s)',
            (request, request, request)).fetchone()
        self.admin.rollback()
        return row

    def test_forms_actual_separated_rights_six_reader_two_reviewer(self):
        for kind, expected in (('reader', 6), ('reviewer', 2), ('issuer', 1)):
            with psycopg.connect(**foundation.CONFIG[kind]) as conn:
                self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0], 'on')
                self.assertEqual(conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='retail' AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')").fetchone()[0], expected)
                self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,'retail.portal_approval_requests_v3','SELECT,INSERT')").fetchone()[0])
                if kind != 'reviewer':
                    self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,"
                        "'retail.api_owner_decide_portal_request_v3(text,text,uuid,uuid,text,text,text,text)','EXECUTE')").fetchone()[0])

    def test_forms_service_issuance_exact_ten_replays_and_no_decision(self):
        case, payload = self.bare_case()
        app, key = self.app(), 'initial-'+uuid4().hex
        status, body, _ = self.issue(app, case, payload, key)
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        for _ in range(10):
            status, replay, _ = self.issue(app, case, payload, key)
            self.assertEqual((status, json.loads(replay)), (200, snapshot))
        self.assertIsNone(snapshot['decision'])
        self.assertEqual(self.bundle_count(snapshot['request']['proposal_id']), (0, 0, 0))
        self.assertEqual(self.issue(app, case, dict(payload, report_payload_sha256='0'*64), key)[0], 409)

    def test_forms_service_validation_auth_duplicates_bounds_do_not_write(self):
        case, payload = self.bare_case()
        app, before = self.app(), self.count()
        for bad in (dict(payload, ttl_seconds=86400), dict(payload, report_revision=True), dict(payload, predecessor_request_id='not-uuid')):
            self.assertEqual(self.issue(app, case, bad)[0], 422)
        self.assertEqual(self.issue(app, case, payload, headers=[(b'host', b'127.0.0.1:18081')])[0], 401)
        self.assertEqual(self.issue(app, case, payload, headers=[(b'authorization', ('Bearer '+foundation.CONFIG['owner_hash']).encode())])[0], 401)
        duplicate = b'{"report_revision":1,"report_revision":1}'
        self.assertEqual(self.issue(app, case, payload, body=duplicate)[0], 422)
        self.assertEqual(self.issue(app, case, payload, body=b'['*1500+b'0'+b']'*1500)[0], 422)
        self.assertEqual(self.issue(app, case, payload, body=b' '*8193)[0], 413)
        self.assertEqual(self.count(), before)

    def test_forms_pending_page_exact_hashes_clock_and_no_view_mutation(self):
        f = self.fixture_portal()
        app, headers, raw = self.browser(f)
        before = self.count()
        for _ in range(3):
            status, body, reply = call(app, self.detail(f), headers=headers)
            self.assertEqual(status, 200)
            self.assertIn(f['snapshot']['request_sha256'].encode(), body)
            self.assertIn(b'original 24-hour deadline', body)
            self.assertIn(b'may commit after the deadline', body)
            self.assertIn(b'Approve exact portal request', body)
            self.assertNotIn(b'Download exact published JSON', body)
            self.assertNotIn(raw.encode(), body)
            self.assertEqual(dict(reply)[b'cache-control'], b'no-store')
        self.assertEqual(self.count(), before)

    def test_forms_confirmed_approval_redirect_receipt_ten_replays_not_publication(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        status, _, reply = self.post(app, f, headers, form)
        self.assertEqual((status, dict(reply)[b'location'].decode()), (303, self.detail(f)))
        for _ in range(10):
            self.assertEqual(self.post(app, f, headers, form)[0], 303)
        status, body, _ = call(app, self.detail(f), headers=headers)
        self.assertEqual(status, 200)
        self.assertIn(b'approved_pending_publication', body)
        self.assertIn(b'Stored owner decision', body)
        self.assertNotIn(b'Approve exact portal request', body)
        self.assertNotIn(b'Download exact published JSON', body)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (1, 1, 0))

    def test_forms_rejection_is_terminal_no_intent_and_conflict_denied(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        form = dict(self.form(app, f, headers), choice='reject')
        self.assertEqual(self.post(app, f, headers, form)[0], 303)
        self.assertEqual(self.post(app, f, headers, dict(form, choice='approve'))[0], 409)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (1, 0, 0))
        self.assertIn(b'rejected', call(app, self.detail(f), headers=headers)[1])

    def test_forms_wrong_bindings_csrf_confirmation_case_never_decide(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        for changed, expected in (({'csrf':'0'*64}, 403), ({'confirm':'no'}, 422), ({'revision':'2'}, 422),
                                  ({'report_sha256':'0'*64}, 409), ({'proposal_sha256':'0'*64}, 409),
                                  ({'target_id':'other'}, 400), ({'choice':'expire'}, 422)):
            self.assertEqual(self.post(app, f, headers, dict(form, **changed))[0], expected)
        wrong = dict(f, case=str(uuid4()))
        self.assertEqual(self.post(app, wrong, headers, form)[0], 409)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (0, 0, 0))

    def test_forms_expiry_after_form_capture_denies_post_readonly_projection(self):
        f = self.fixture_portal(seconds=1.2)
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        self.wait_expired(f['snapshot']['request']['proposal_id'])
        self.assertEqual(self.post(app, f, headers, form)[0], 409)
        body = call(app, self.detail(f), headers=headers)[1]
        self.assertIn(b'fresh owner approval', body)
        self.assertNotIn(b'Approve exact portal request', body)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (0, 0, 0))

    def test_forms_expired_approved_successor_service_and_historical_receipts(self):
        f = self.fixture_portal(seconds=1.2)
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        self.assertEqual(self.post(app, f, headers, form)[0], 303)
        parent = f['snapshot']['request']['proposal_id']
        self.wait_expired(parent)
        self.assertIn(b'approved_expired', call(app, self.detail(f), headers=headers)[1])
        payload = {'report_revision':1, 'report_payload_sha256':form['report_sha256'], 'predecessor_request_id':parent}
        status, body, _ = self.issue(app, f['case'], payload)
        self.assertEqual(status, 200)
        successor = json.loads(body)
        self.assertEqual(successor['request']['generation'], 2)
        self.assertIsNone(successor['decision'])
        fresh = dict(f, snapshot=successor)
        historical = call(app, self.detail(f), headers=headers)[1]
        self.assertIn(b'superseded', historical)
        self.assertIn(form['decision_key'].encode(), historical)
        self.assertNotIn(b'Approve exact portal request', historical)
        self.assertEqual(self.post(app, f, headers, dict(form, decision_key='new-'+uuid4().hex))[0], 409)
        fresh_form = self.form(app, fresh, headers)
        self.assertNotEqual(fresh_form['proposal_sha256'], form['proposal_sha256'])
        self.assertEqual(self.post(app, fresh, headers, fresh_form)[0], 303)
        self.assertEqual(self.bundle_count(successor['request']['proposal_id']), (1, 1, 0))
        index = call(app, '/portal', headers=headers)[1]
        self.assertIn(self.detail(fresh).encode(), index)
        self.assertNotIn(self.detail(f).encode(), index)

    def test_forms_committed_publication_link_and_exact_export(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        self.assertEqual(self.post(app, f, headers, self.form(app, f, headers))[0], 303)
        value = self.review_store().review(f['session'], f['case'], f['snapshot']['request']['proposal_id'])
        self.store().accept(value['action_id'], 'forms-publish-'+uuid4().hex)
        before = self.count()
        body = call(app, self.detail(f), headers=headers)[1]
        self.assertIn(b'Committed publication', body)
        self.assertIn(b'Download exact published JSON', body)
        self.assertNotIn(b'Approve exact portal request', body)
        self.assertEqual(call(app, self.path(value['action_id'], True), headers=headers)[:2],
                         (200, foundation.CONFIG['base']['report'].encode()))
        self.assertEqual(self.count(), before)

    def test_forms_deferred_commit_fault_no_success_redirect_or_bundle(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        self.admin.execute("CREATE FUNCTION pg_temp.fail_forms_commit() RETURNS trigger LANGUAGE plpgsql AS $$ "
                           "BEGIN RAISE EXCEPTION 'Synthetic forms deferred fault'; END $$")
        self.admin.execute('CREATE CONSTRAINT TRIGGER portal_forms_test_fault AFTER INSERT ON retail.portal_review_decisions_v2 '
                           'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_forms_commit()')
        self.admin.commit()
        try:
            status, body, reply = self.post(app, f, headers, form)
            self.assertEqual(status, 503)
            self.assertNotIn(b'location', dict(reply))
            self.assertNotIn(form['csrf'].encode(), body)
            self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (0, 0, 0))
        finally:
            self.admin.execute('DROP TRIGGER portal_forms_test_fault ON retail.portal_review_decisions_v2')
            self.admin.commit()

    def test_forms_real_decision_commit_simulated_lost_ack_get_before_same_key_replay(self):
        f = self.fixture_portal()
        review = self.review_store()
        app, headers, _ = self.browser(f)
        app = self.app(review)
        form = self.form(app, f, headers)
        original_factory = review.reviewer.factory
        def once():
            review.reviewer.factory = original_factory
            return CommitFault(original_factory(), True)
        review.reviewer.factory = once
        self.assertEqual(self.post(app, f, headers, form)[0], 503)
        self.assertIn(b'Stored owner decision', call(app, self.detail(f), headers=headers)[1])
        self.assertEqual(self.post(app, f, headers, form)[0], 303)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (1, 1, 0))

    def test_forms_concurrent_same_key_independent_store_single_bundle(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        barrier = threading.Barrier(2)
        def run(_):
            local = self.app()
            barrier.wait(timeout=5)
            return self.post(local, f, headers, form)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(run, range(2)))
        self.assertIn(303, statuses)
        self.assertTrue(all(status in (303, 429) for status in statuses))
        self.assertEqual(self.post(app, f, headers, form)[0], 303)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (1, 1, 0))

    def test_forms_historical_same_key_after_expiry_is_not_new_authorization(self):
        f = self.fixture_portal(seconds=1.2)
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        self.assertEqual(self.post(app, f, headers, form)[0], 303)
        self.wait_expired(f['snapshot']['request']['proposal_id'])
        self.assertEqual(self.post(app, f, headers, form)[0], 303)
        self.assertIn(b'approved_expired', call(app, self.detail(f), headers=headers)[1])
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (1, 1, 0))

    def test_forms_concurrent_opposite_choices_one_terminal_winner(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        barrier = threading.Barrier(2)
        def run(choice):
            local = self.app()
            selected = dict(form, choice=choice, decision_key='opposite-'+uuid4().hex)
            barrier.wait(timeout=5)
            return choice, self.post(local, f, headers, selected)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ('approve', 'reject')))
        self.assertEqual(sum(status==303 for _,status in results), 1)
        self.assertTrue(all(status in (303, 409, 429) for _,status in results))
        choice = next(choice for choice,status in results if status==303)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (1, int(choice=='approve'), 0))

    def test_forms_expired_session_cannot_submit_captured_decision(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f, expired=True)
        # A stale captured form cannot be turned into a new decision.
        form = {'csrf':'0'*64, 'revision':'1', 'report_sha256':f['snapshot']['request']['report_payload_sha256'],
                'proposal_sha256':f['snapshot']['request_sha256'], 'decision_key':'stale-'+uuid4().hex,
                'choice':'approve', 'confirm':'yes'}
        self.assertEqual(self.post(app, f, headers, form)[0], 401)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (0, 0, 0))

    def test_forms_legacy_target_cannot_issue_or_be_adopted(self):
        old = self.fixture()
        case = str(self.admin.execute('SELECT case_id FROM retail.publication_outbox_v1 WHERE action_id=%s', (old['action_id'],)).fetchone()[0])
        self.admin.rollback()
        payload = {'report_revision':1, 'report_payload_sha256':old['content_sha256'], 'predecessor_request_id':None}
        self.assertEqual(self.issue(self.app(), case, payload)[0], 409)

    def test_forms_browser_denials_duplicate_fields_body_origin_no_effect(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        path = self.detail(f)+'/decision'
        self.assertEqual(call(app, path, method='POST', body=urlencode(form).encode(), headers=headers)[0], 403)
        base = headers+[(b'origin', b'http://127.0.0.1:18081'), (b'content-type', b'application/x-www-form-urlencoded')]
        self.assertEqual(call(app, path, method='POST', body=urlencode(form).encode()+b'&choice=reject', headers=base)[0], 400)
        self.assertEqual(call(app, path, method='POST', body=b'x'*2049, headers=base)[0], 413)
        self.assertEqual(call(app, path, method='POST', body=urlencode(form).encode(), headers=base+[(b'authorization', b'Bearer service')])[0], 400)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']), (0, 0, 0))

    def test_forms_untrusted_stored_text_is_escaped_not_interpreted(self):
        original = foundation.CONFIG['base']['report']
        malicious = json.loads(original)
        malicious['untrusted_text'] = '<script>steal()</script><img src="https://evil.invalid"><form action="https://evil.invalid">'
        canonical = self.admin.execute('SELECT %s::jsonb::text', (json.dumps(malicious),)).fetchone()[0]
        self.admin.rollback()
        foundation.CONFIG['base']['report'] = canonical
        try:
            f = self.fixture_portal()
        finally:
            foundation.CONFIG['base']['report'] = original
        app, headers, _ = self.browser(f)
        status, body, _ = call(app, self.detail(f), headers=headers)
        self.assertEqual(status, 200)
        self.assertNotIn(b'<script>', body)
        self.assertNotIn(b'<img', body)
        self.assertIn(b'&lt;script&gt;', body)

    def test_forms_zz_revoked_owner_denies_new_controls_and_service_issuance(self):
        f = self.fixture_portal()
        app, headers, _ = self.browser(f)
        form = self.form(app, f, headers)
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s', (self.owner,))
        self.admin.commit()
        self.assertEqual(call(app, self.detail(f), headers=headers)[0], 303)
        self.assertEqual(self.post(app, f, headers, form)[0], 401)
        payload = {'report_revision':1, 'report_payload_sha256':form['report_sha256'], 'predecessor_request_id':None}
        self.assertEqual(self.issue(app, f['case'], payload)[0], 401)


if __name__ == '__main__':
    foundation.CONFIG = json.loads(sys.stdin.read())
    ReviewV3Tests.__unittest_skip__ = False
    suite = unittest.TestSuite(ReviewV3Tests(name) for name in dir(ReviewV3Tests) if name.startswith('test_forms_'))
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
    print(json.dumps({'passed':result.wasSuccessful(), 'tests_run':result.testsRun,
        'failed_tests':[getattr(t, '_testMethodName', 'class_setup') for t,_ in result.errors+result.failures],
        'error_types':result.error_types, 'sqlstates':result.sqlstates, 'constraints':result.constraints}))
