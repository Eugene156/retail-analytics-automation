"""Private isolated SQL/ASGI worker tests; not actual n8n execution evidence."""
from concurrent.futures import ThreadPoolExecutor
import copy
import io
import json
import re
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch

import psycopg
from fastapi import FastAPI
from api.portal_worker_v2 import IsolatedPortalWorker, install_isolated_worker_v2
from test_wp4_portal_publication_reads_database import PublicationReadTests, CommitFault
from test_wp4_portal import call
import test_wp4_dispatch_database as foundation


@unittest.skipUnless(foundation.CONFIG is not None,'Private isolated database input required')
class WorkerTests(PublicationReadTests):
    def worker_api(self,factory=None):
        return IsolatedPortalWorker(self.store('portal_worker',factory))

    def app(self,worker=None):
        app=FastAPI()
        install_isolated_worker_v2(app,worker or self.worker_api(),foundation.CONFIG['worker_token'])
        return app

    def approved(self,seconds=None):
        f=self.fixture_portal(seconds=seconds); saved=self.decide_portal(f)
        return dict(f,saved=saved,action=saved['action_id'],key='worker-'+uuid4().hex)

    def headers(self,f,post=False):
        return [(b'host',b'raa-wp4-portal-test:8000'),(b'authorization',b'Bearer '+foundation.CONFIG['worker_token'].encode()),
                (b'idempotency-key',f['key'].encode())]+([(b'content-type',b'application/json')] if post else [])

    def payload(self,f):
        return {'case_id':f['case'],'request_sha256':f['saved']['request_sha256'],
                'report_sha256':f['saved']['request']['report_payload_sha256']}

    def path(self,f,post=False):
        return '/api/v3/portal-actions/'+f['action']+('/accept' if post else '')

    def read(self,app,f):
        return call(app,self.path(f),headers=self.headers(f))

    def post(self,app,f,payload=None,headers=None,body=None):
        return call(app,self.path(f,True),'POST',json.dumps(payload or self.payload(f)).encode() if body is None else body,
                    self.headers(f,True) if headers is None else headers)

    def counts(self,f):
        row=self.admin.execute('SELECT (SELECT count(*) FROM retail.portal_publications_v2 WHERE action_id=%s),'
            "(SELECT count(*) FROM retail.portal_publication_audit_v2 a JOIN retail.portal_publications_v2 p ON a.subject_id=p.publication_id WHERE p.action_id=%s)",
            (f['action'],f['action'])).fetchone(); self.admin.rollback(); return row

    def test_worker_01_actual_two_fixed_functions_no_auth_review_legacy_tables(self):
        with psycopg.connect(**foundation.CONFIG['portal_worker']) as conn:
            self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0],'on')
            self.assertEqual(conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='retail' AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')").fetchone()[0],2)
            for tab in ('portal_publications_v2','owner_credentials','portal_review_decisions_v2','publication_outbox_v1'):
                self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE')",('retail.'+tab,)).fetchone()[0])
            for fn in ('api_accept_portal_publication_v2(uuid,text)','api_portal_auth_login_v2(text,text,text,text)',
                       'api_decide_portal_request_v2(text,text,uuid,text,text,text)','api_claim_publication_v1(uuid,text,text)'):
                self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')",('retail.'+fn,)).fetchone()[0])

    def test_worker_02_read_commit_accept_ten_replays_exact_export_no_duplicate(self):
        f=self.approved(); app=self.app()
        before=self.read(app,f); self.assertEqual(before[0],200)
        self.assertEqual(json.loads(before[1])['status'],'pending'); self.assertEqual(self.counts(f),(0,0))
        self.assertEqual(self.post(app,f)[0],200)
        for _ in range(10):
            self.assertEqual(self.post(app,f)[0],200)
            state=json.loads(self.read(app,f)[1]); self.assertEqual(state['status'],'published')
            self.assertTrue(state['key_bound']); self.assertEqual(state['acceptance_key'],f['key'])
        self.assertEqual(self.counts(f),(1,1))
        _,headers,raw=self.browser(f)
        from api.portal import digest
        receipt,body=self.store('reader').publication(digest(raw),f['action'],True)
        self.assertEqual(body,foundation.CONFIG['base']['report'].encode()); self.assertEqual(receipt['action_id'],f['action'])

    def test_worker_03_auth_before_bad_body_and_owner_service_substitution(self):
        f=self.approved(); app=self.app()
        for token in (foundation.CONFIG['service_token'],foundation.CONFIG['owner_token'],'0'*64):
            headers=[(b'authorization',b'Bearer '+token.encode())]
            self.assertEqual(self.post(app,f,headers=headers,body=b'x'*9000)[0],401)
        self.assertEqual(self.post(app,f,headers=self.headers(f,True)+[(b'authorization',b'Bearer '+foundation.CONFIG['worker_token'].encode())])[0],401)
        self.assertEqual(self.counts(f),(0,0))

    def test_worker_04_strict_binding_no_target_clock_ttl_or_duplicate_fields(self):
        f=self.approved(); app=self.app(); payload=self.payload(f)
        for changed in (dict(payload,ttl=86400),dict(payload,target_id='local-approved-report-json-v1'),
                        dict(payload,accepted_at='2026-10-06T00:00:00Z'),dict(payload,report_sha256='bad')):
            self.assertEqual(self.post(app,f,changed)[0],422)
        self.assertEqual(self.post(app,f,body=b'{"case_id":"x","case_id":"y"}')[0],422)
        self.assertEqual(self.post(app,f,body=b'['*1100+b']'*1100)[0],422)
        self.assertEqual(self.post(app,f,body=b'x'*8193)[0],413)
        self.assertEqual(self.counts(f),(0,0))

    def test_worker_05_wrong_case_request_report_hash_denied_without_effect(self):
        f=self.approved(); app=self.app()
        for name,value in (('case_id',str(uuid4())),('request_sha256','0'*64),('report_sha256','0'*64)):
            self.assertEqual(self.post(app,f,dict(self.payload(f),**{name:value}))[0],409)
        self.assertEqual(self.counts(f),(0,0))

    def test_worker_06_expired_approved_requires_new_request_no_acceptance(self):
        f=self.approved(seconds=1); self.wait_expired(f['saved']['request']['proposal_id']); app=self.app()
        self.assertEqual(json.loads(self.read(app,f)[1])['status'],'expired')
        self.assertEqual(self.post(app,f)[0],409); self.assertEqual(self.counts(f),(0,0))

    def test_worker_07_original_committed_key_only_changed_key_conflicts(self):
        f=self.approved(); app=self.app(); self.assertEqual(self.post(app,f)[0],200)
        changed=dict(f,key='changed-'+uuid4().hex)
        self.assertEqual(self.read(app,changed)[0],409); self.assertEqual(self.post(app,changed)[0],409)
        self.assertEqual(self.counts(f),(1,1))

    def test_worker_08_missing_or_legacy_action_cannot_create_approval(self):
        app=self.app(); f=self.approved(); missing=dict(f,action=str(uuid4()))
        self.assertEqual(self.read(app,missing)[0],404); self.assertEqual(self.post(app,missing)[0],404)
        old=self.fixture(); legacy=dict(f,action=str(old['action_id']))
        self.assertEqual(self.read(app,legacy)[0],404); self.assertEqual(self.post(app,legacy)[0],404)
        self.assertEqual(self.counts(f),(0,0))

    def test_worker_09_uncommitted_acceptance_busy_then_rollback_pending(self):
        f=self.approved(); app=self.app()
        with psycopg.connect(**foundation.CONFIG['portal_worker']) as conn:
            conn.read_only=False
            conn.execute('SELECT retail.api_worker_accept_portal_v2(%s,%s,%s,%s,%s)',
                (f['action'],f['key'],f['case'],self.payload(f)['request_sha256'],self.payload(f)['report_sha256']))
            self.assertEqual(self.read(app,f)[0],429); self.assertEqual(self.counts(f),(0,0)); conn.rollback()
        self.assertEqual(json.loads(self.read(app,f)[1])['status'],'pending')

    def test_worker_10_precommit_fault_no_published_response_then_pending(self):
        f=self.approved(); bad=self.app(self.worker_api(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['portal_worker']),False)))
        self.assertEqual(self.post(bad,f)[0],503); self.assertEqual(self.counts(f),(0,0))
        self.assertEqual(json.loads(self.read(self.app(),f)[1])['status'],'pending')

    def test_worker_11_real_commit_simulated_ack_loss_reconcile_original_no_rewrite(self):
        f=self.approved(); bad=self.app(self.worker_api(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['portal_worker']),True)))
        self.assertEqual(self.post(bad,f)[0],503); self.assertEqual(self.counts(f),(1,1))
        good=self.app(); state=json.loads(self.read(good,f)[1]); self.assertEqual(state['status'],'published')
        self.assertEqual(self.post(good,f)[0],200); self.assertEqual(self.counts(f),(1,1))

    def test_worker_12_actual_audit_fault_rolls_back_publication(self):
        f=self.approved(); self.admin.execute("CREATE FUNCTION pg_temp.worker_audit_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Synthetic audit fault'; END $$")
        self.admin.execute('CREATE TRIGGER worker_test_fault BEFORE INSERT ON retail.portal_publication_audit_v2 '
                           'FOR EACH ROW EXECUTE FUNCTION pg_temp.worker_audit_fault()'); self.admin.commit()
        try:
            self.assertEqual(self.post(self.app(),f)[0],503); self.assertEqual(self.counts(f),(0,0))
        finally:
            self.admin.execute('DROP TRIGGER worker_test_fault ON retail.portal_publication_audit_v2'); self.admin.commit()

    def test_worker_13_bad_return_validation_before_commit_rolls_back(self):
        f=self.approved(); worker=self.worker_api(); actual=worker.validate
        def invalid(value,*args,**kwargs):
            changed=copy.deepcopy(value); changed['snapshot']['request_sha256']='0'*64
            return actual(changed,*args,**kwargs)
        with patch.object(worker,'validate',side_effect=invalid):
            self.assertEqual(self.post(self.app(worker),f)[0],503)
        self.assertEqual(self.counts(f),(0,0))

    def test_worker_14_two_concurrent_same_key_workers_one_publication(self):
        f=self.approved()
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.post(self.app(),f)[0],range(2)))
        self.assertTrue(all(s in (200,429) for s in results)); self.assertIn(200,results)
        self.assertEqual(self.post(self.app(),f)[0],200); self.assertEqual(self.counts(f),(1,1))

    def test_worker_15_browser_headers_query_and_duplicate_key_denied(self):
        f=self.approved(); app=self.app()
        for extra in ((b'cookie',b'x=y'),(b'origin',b'http://127.0.0.1:18081')):
            self.assertEqual(self.post(app,f,headers=self.headers(f,True)+[extra])[0],400)
        self.assertEqual(self.post(app,f,headers=self.headers(f,True)+[(b'idempotency-key',b'another-key')])[0],422)
        self.assertEqual(call(app,self.path(f),headers=self.headers(f),query=b'x=1')[0],400)
        self.assertEqual(self.counts(f),(0,0))

    def test_worker_16_existing_timely_publication_read_and_replay_after_deadline(self):
        f=self.approved(seconds=1); app=self.app()
        self.assertEqual(self.post(app,f)[0],200)
        self.wait_expired(f['saved']['request']['proposal_id'])
        self.assertEqual(json.loads(self.read(app,f)[1])['status'],'published')
        self.assertEqual(self.post(app,f)[0],200); self.assertEqual(self.counts(f),(1,1))

    def test_worker_zz_owner_revocation_blocks_state_and_acceptance(self):
        f=self.approved(); app=self.app()
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s',(self.owner,)); self.admin.commit()
        self.assertEqual(self.read(app,f)[0],401); self.assertEqual(self.post(app,f)[0],401)
        self.assertEqual(self.counts(f),(0,0))


if __name__=='__main__':
    foundation.CONFIG=json.loads(sys.stdin.read()); WorkerTests.__unittest_skip__=False
    names=[n for n in dir(WorkerTests) if n.startswith('test_worker_') and n!='test_worker_zz_owner_revocation_blocks_state_and_acceptance']
    names += [n for n in dir(WorkerTests) if n.startswith('test_portal_') and 'zz_' not in n]
    names += ['test_worker_zz_owner_revocation_blocks_state_and_acceptance']
    suite=unittest.TestSuite(WorkerTests(n) for n in names)
    class PrivateResult(unittest.TextTestResult):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw); self.error_types=[]; self.sqlstates=[]; self.constraints=[]
        def addError(self,t,e):
            self.error_types.append(e[0].__name__); self.sqlstates.append(getattr(e[1],'sqlstate',None) or 'none')
            name=getattr(getattr(e[1],'diag',None),'constraint_name',None)
            self.constraints.append(name if isinstance(name,str) and re.fullmatch(r'[a-z0-9_]{1,128}',name) else 'none'); super().addError(t,e)
    r=unittest.TextTestRunner(stream=io.StringIO(),resultclass=PrivateResult).run(suite)
    print(json.dumps({'passed':r.wasSuccessful(),'tests_run':r.testsRun,'failed_tests':[getattr(t,'_testMethodName','setup') for t,_ in r.errors+r.failures],
                      'error_types':r.error_types,'sqlstates':r.sqlstates,'constraints':r.constraints}))
