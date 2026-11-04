"""Private SQL/ASGI transition API/provenance tests, not socket/browser evidence."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import copy
import io
import json
import re
import sys
import threading
import unittest
from uuid import uuid4

import psycopg
from fastapi import FastAPI, HTTPException
from api.portal_transition_v1 import IsolatedPortalTransition, install_isolated_transition_v1
from test_wp4_portal_transition_database import TransitionTests
from test_wp4_portal_publication_reads_database import CommitFault
from test_wp4_portal import call
import test_wp4_dispatch_database as foundation


@unittest.skipUnless(foundation.CONFIG is not None, 'Private isolated database input required')
class TransitionAPITests(TransitionTests):
    def review_store(self):
        return IsolatedPortalTransition(self.store('reader'), self.store('reviewer'), self.store('issuer'), self.store('transition'))

    def app(self, review=None):
        app = FastAPI()
        install_isolated_transition_v1(app, review or self.review_store(), foundation.CONFIG['portal_key'],foundation.CONFIG['service_token'])
        return app

    def service_headers(self,key,post=False):
        headers=[(b'host',b'127.0.0.1:18081'),(b'authorization',('Bearer '+foundation.CONFIG['service_token']).encode()),
                 (b'idempotency-key',key.encode())]
        return headers+([(b'content-type',b'application/json')] if post else [])

    def payload(self,f):
        return dict(report_revision=1,report_payload_sha256=f['report_hash'],legacy_request_id=f['old'],legacy_request_sha256=f['old_hash'])

    def path_transition(self,f):
        return '/api/v3/cases/'+f['case']+'/portal-transition'

    def path_legacy(self,f):
        return '/portal/legacy/cases/'+f['case']+'/requests/'+f['old']

    def path_evidence(self,f):
        return '/portal/cases/'+f['case']+'/transition'

    def transition_post(self,app,f,key,payload=None,headers=None,body=None,chunks=None,query=b''):
        return call(app,self.path_transition(f),'POST',json.dumps(payload or self.payload(f)).encode() if body is None else body,
                    self.service_headers(key,True) if headers is None else headers,chunks=chunks,query=query)

    def transition_get(self,app,f,key):
        return call(app,self.path_transition(f),headers=self.service_headers(key))

    def test_api_actual_roles_two_transition_eight_reader_no_business_tables(self):
        for kind,expected in (('transition',2),('reader',8),('reviewer',2),('issuer',1)):
            with psycopg.connect(**foundation.CONFIG[kind]) as conn:
                self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0],'on')
                self.assertEqual(conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='retail' AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')").fetchone()[0],expected)
                for tab in ('portal_legacy_transitions_v1','approval_requests_v2','portal_publications_v2'):
                    self.assertFalse(conn.execute('SELECT has_table_privilege(current_user,%s,\'SELECT,INSERT,UPDATE\')',('retail.'+tab,)).fetchone()[0])
                if kind!='transition':
                    self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,'retail.api_transition_legacy_portal_v1(uuid,uuid,text,text,text)','EXECUTE')").fetchone()[0])

    def test_api_explicit_transition_commit_location_ten_replays_no_approval(self):
        f,key=self.legacy_fixture(),'api-transition-'+uuid4().hex
        app=self.app()
        status,body,headers=self.transition_post(app,f,key)
        self.assertEqual(status,200)
        value=json.loads(body)
        self.assertEqual(dict(headers)[b'location'].decode(),self.detail(self.new_fixture(f,value)))
        self.assertEqual(dict(headers)[b'x-decision-enabled'],b'false')
        for _ in range(10):
            self.assertEqual(self.transition_post(app,f,key)[:2],(200,body))
            self.assertEqual(self.transition_get(app,f,key)[:2],(200,body))
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))
        self.assertEqual(self.bundle_count(value['transition']['first_request_id']),(0,0,0))
        self.assert_old_preserved(f)

    def test_api_get_before_transition_or_wrong_key_no_write(self):
        f,key=self.legacy_fixture(),'inspect-'+uuid4().hex
        app=self.app()
        self.assertEqual(self.transition_get(app,f,key)[0],404)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))
        self.assertEqual(self.transition_post(app,f,key)[0],200)
        self.assertEqual(self.transition_get(app,f,'wrong-'+uuid4().hex)[0],409)
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))

    def test_api_auth_precedes_parsing_owner_cookie_and_token_not_service(self):
        f,key=self.legacy_fixture(),'auth-'+uuid4().hex
        app,owner_headers,_=self.browser(f)
        self.assertEqual(self.transition_post(app,f,key,headers=owner_headers,body=b'not JSON')[0],401)
        for token in (foundation.CONFIG['owner_hash'],'0'*64):
            headers=[(b'authorization',('Bearer '+token).encode())]
            self.assertEqual(self.transition_post(app,f,key,headers=headers,body=b'x'*8193)[0],401)
        headers=self.service_headers(key,True)
        self.assertEqual(self.transition_post(app,f,key,headers=headers+[(b'authorization',headers[1][1])])[0],401)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))

    def test_api_strict_payload_no_target_owner_ttl_path_time_overrides(self):
        f,key=self.legacy_fixture(),'validation-'+uuid4().hex
        app=self.app(); payload=self.payload(f)
        invalid=[dict(payload,**{field:override}) for field,override in (
            ('target_id','other'),('reviewer_id',str(uuid4())),('ttl_seconds',172800),
            ('created_at','2026-10-05T00:00:00Z'),('path','elsewhere'),('report_revision',True),
            ('legacy_request_id','not-uuid'),('legacy_request_sha256',None),('report_payload_sha256','BAD'))]
        invalid.extend([{},[],None])
        for bad in invalid:
            self.assertEqual(self.transition_post(app,f,key,body=json.dumps(bad).encode())[0],422)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))

    def test_api_duplicate_deep_large_chunked_json_and_headers_denied(self):
        f,key=self.legacy_fixture(),'wire-'+uuid4().hex
        app=self.app(); headers=self.service_headers(key,True)
        for body,status in ((b'{"report_revision":1,"report_revision":1}',422),
                            (b'['*1500+b'0'+b']'*1500,422),(b' '*8193,413),(b'\xff',422)):
            self.assertEqual(self.transition_post(app,f,key,body=body)[0],status)
        self.assertEqual(self.transition_post(app,f,key,chunks=[b'a'*4096,b'b'*4097])[0],413)
        self.assertEqual(self.transition_post(app,f,key,headers=headers+[(b'idempotency-key',key.encode())])[0],422)
        self.assertEqual(self.transition_post(app,f,key,headers=[h for h in headers if h[0]!=b'idempotency-key'])[0],422)
        self.assertEqual(self.transition_post(app,f,key,headers=headers+[(b'content-type',b'application/json')])[0],422)
        self.assertEqual(self.transition_post(app,f,key,query=b'ttl=172800')[0],422)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))

    def test_api_live_stale_reviewed_wrong_hash_and_changed_key_denied(self):
        app=self.app()
        live=self.legacy_fixture(seconds=3600)
        self.assertEqual(self.transition_post(app,live,'live-'+uuid4().hex)[0],409)
        f=self.legacy_fixture()
        with self.connect('legacy') as conn: self.legacy_issue(f,'new-old-'+uuid4().hex,conn)
        self.assertEqual(self.transition_post(app,f,'stale-'+uuid4().hex)[0],409)
        reviewed=self.legacy_fixture()
        with self.connect('legacy') as conn: self.legacy_decide(reviewed,'expire',conn)
        self.assertEqual(self.transition_post(app,reviewed,'reviewed-'+uuid4().hex)[0],409)
        f,key=self.legacy_fixture(),'bind-'+uuid4().hex
        for field in ('report_payload_sha256','legacy_request_sha256'):
            self.assertEqual(self.transition_post(app,f,key,dict(self.payload(f),**{field:'0'*64}))[0],409)
        self.assertEqual(self.transition_post(app,f,key)[0],200)
        self.assertEqual(self.transition_post(app,f,'different-'+uuid4().hex)[0],409)
        self.assert_old_preserved(f)

    def test_api_service_browser_headers_denied_no_transition(self):
        f,key=self.legacy_fixture(),'service-only-'+uuid4().hex
        app,owner_headers,_=self.browser(f)
        for extra in ((b'cookie',owner_headers[1][1]),(b'origin',b'http://127.0.0.1:18081')):
            self.assertEqual(self.transition_post(app,f,key,headers=self.service_headers(key,True)+[extra])[0],400)
            self.assertEqual(call(app,self.path_transition(f),headers=self.service_headers(key)+[extra])[0],400)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))

    def test_api_owner_new_review_provenance_before_confirmed_form(self):
        f,key=self.legacy_fixture(),'owner-context-'+uuid4().hex
        value=json.loads(self.transition_post(self.app(),f,key)[1])
        fresh=self.new_fixture(f,value)
        app,headers,raw=self.browser(fresh)
        before=self.counts(f['case'])
        status,body,reply=call(app,self.detail(fresh),headers=headers)
        self.assertEqual(status,200)
        for wanted in (f['old_hash'],value['transition_sha256'],value['transition']['first_request_sha256'],
                       self.path_legacy(f),'No legacy approval was transferred','no legacy file was adopted'):
            self.assertIn(wanted.encode(),body)
        self.assertLess(body.index(b'Legacy target retired'),body.index(b'<form'))
        self.assertNotIn(raw.encode(),body); self.assertEqual(dict(reply)[b'cache-control'],b'no-store')
        self.assertEqual(self.counts(f['case']),before)
        self.assertEqual(self.post(app,fresh,headers,self.form(app,fresh,headers))[0],303)
        self.assertEqual(self.bundle_count(value['transition']['first_request_id']),(1,1,0))
        self.assert_old_preserved(f)

    def test_api_owner_committed_evidence_and_legacy_page_readonly_exact(self):
        f,key=self.legacy_fixture(),'legacy-page-'+uuid4().hex
        value=self.transition(f,key)
        app,headers,raw=self.browser(f)
        before=self.counts(f['case'])
        for path in (self.path_evidence(f),self.path_legacy(f)):
            for _ in range(3):
                status,body,reply=call(app,path,headers=headers)
                self.assertEqual(status,200)
                self.assertIn(b'decisions disabled',body)
                self.assertEqual(dict(reply)[b'x-decision-enabled'],b'false')
                self.assertNotIn(b'<form',body); self.assertNotIn(b'Download exact published JSON',body)
                self.assertNotIn(raw.encode(),body)
                self.assertIn(value['transition_sha256'].encode(),body)
        history=self.review_store().legacy(f['session'],f['case'],f['old'])
        self.assertEqual(history['legacy_request']['canonical_payload_text'],f['old_text'])
        self.assertEqual(self.counts(f['case']),before); self.assert_old_preserved(f)

    def test_api_legacy_and_evidence_uncommitted_invisible_then_visible(self):
        f,key=self.legacy_fixture(),'visibility-'+uuid4().hex
        app,headers,_=self.browser(f)
        with self.connect('transition') as writer:
            self.transition(f,key,writer)
            self.assertEqual(self.transition_get(app,f,key)[0],429)
            for path in (self.path_evidence(f),self.path_legacy(f)):
                self.assertEqual(call(app,path,headers=headers)[0],404)
        for path in (self.path_evidence(f),self.path_legacy(f)):
            self.assertEqual(call(app,path,headers=headers)[0],200)

    def test_api_wrong_case_old_request_and_clean_case_no_provenance(self):
        f=self.legacy_fixture(); self.transition(f,'scope-'+uuid4().hex)
        other=self.legacy_fixture()
        app,headers,_=self.browser(f)
        wrong=dict(f,old=other['old'])
        self.assertEqual(call(app,self.path_legacy(wrong),headers=headers)[0],404)
        self.assertEqual(call(app,self.path_evidence(other),headers=headers)[0],404)
        clean=self.fixture_portal()
        body=call(app,self.detail(clean),headers=headers)[1]
        self.assertIn(b'Approve exact portal request',body)
        self.assertNotIn(b'Legacy target retired',body)

    def test_api_historical_earlier_legacy_request_retired_without_rewrite(self):
        f=self.legacy_fixture(seconds=-86401)
        # Privileged synthetic generation 2 with a fully expired original TTL.
        pid,key=str(uuid4()),'prior-chain-'+uuid4().hex
        created=self.admin.execute("SELECT clock_timestamp()-interval '86401 seconds'").fetchone()[0]
        size=len(foundation.CONFIG['base']['report'].encode())
        body=self.admin.execute("SELECT retail.approval_request_payload_v2(%s,%s,1,%s,%s,%s,%s,%s+interval '86400 seconds',2,%s,%s,%s)",
            (pid,f['case'],f['report_hash'],size,self.owner,created,created,key,f['old'],f['old_hash'])).fetchone()[0]
        self.admin.execute("INSERT INTO retail.approval_requests_v2 VALUES(%s,%s,1,2,%s,%s,%s,'local-publication-v1',%s,%s,%s,%s,%s+interval '86400 seconds',%s,%s)",
            (pid,f['case'],key,f['old'],f['old_hash'],self.owner,f['report_hash'],size,created,created,body,sha256(body.encode()).hexdigest()))
        self.admin.execute('INSERT INTO retail.approval_request_events_v2(proposal_id,occurred_at) VALUES(%s,%s)',(pid,created)); self.admin.commit()
        latest=dict(f,old=pid,old_hash=sha256(body.encode()).hexdigest(),old_text=body)
        self.transition(latest,'prior-transition-'+uuid4().hex)
        app,headers,_=self.browser(f)
        self.assertEqual(call(app,self.path_legacy(f),headers=headers)[0],200)
        self.assertEqual(self.review_store().legacy(f['session'],f['case'],f['old'])['legacy_request']['canonical_payload_text'],f['old_text'])
        self.assert_old_preserved(latest); self.assert_old_preserved(f)

    def test_api_concurrent_service_stores_same_key_single_bundle(self):
        f,key=self.legacy_fixture(),'api-concurrent-'+uuid4().hex
        barrier=threading.Barrier(2)
        def run(_):
            app=self.app(); barrier.wait(timeout=5)
            return self.transition_post(app,f,key)[0]
        with ThreadPoolExecutor(max_workers=2) as pool: statuses=list(pool.map(run,range(2)))
        self.assertIn(200,statuses); self.assertTrue(all(status in (200,429) for status in statuses))
        self.assertEqual(self.transition_get(self.app(),f,key)[0],200)
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))

    def test_api_deferred_fault_no_success_location_and_no_retirement(self):
        f,key=self.legacy_fixture(),'api-fault-'+uuid4().hex
        self.admin.execute("CREATE FUNCTION pg_temp.transition_api_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Synthetic transition API fault'; END $$")
        self.admin.execute('CREATE CONSTRAINT TRIGGER portal_transition_api_test_fault AFTER INSERT ON retail.portal_legacy_transitions_v1 '
            'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION pg_temp.transition_api_fault()'); self.admin.commit()
        app=self.app()
        try:
            status,body,headers=self.transition_post(app,f,key)
            self.assertEqual(status,503); self.assertNotIn(b'location',dict(headers))
            self.assertNotIn(foundation.CONFIG['service_token'].encode(),body)
            self.assertEqual(self.counts(f['case']),(0,0,0,0,0))
            self.assertEqual(self.transition_get(app,f,key)[0],404)
        finally:
            self.admin.execute('DROP TRIGGER portal_transition_api_test_fault ON retail.portal_legacy_transitions_v1'); self.admin.commit()

    def test_api_real_commit_simulated_lost_ack_service_get_before_replay(self):
        f,key=self.legacy_fixture(),'api-ack-'+uuid4().hex
        store=self.review_store(); original=store.transition_store.factory
        def once():
            store.transition_store.factory=original
            return CommitFault(original(),True)
        store.transition_store.factory=once
        app=self.app(store)
        status,body,headers=self.transition_post(app,f,key)
        self.assertEqual(status,503); self.assertNotIn(b'location',dict(headers))
        self.assertIn(b'inspect',body)
        status,observed,_=self.transition_get(app,f,key)
        self.assertEqual(status,200)
        self.assertEqual(self.transition_post(app,f,key)[:2],(200,observed))
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))

    def test_api_invalid_result_validation_rolls_back_actual_transition(self):
        f,key=self.legacy_fixture(),'bad-result-'+uuid4().hex
        store=self.review_store()
        store.validate_transition=lambda *args: (_ for _ in ()).throw(HTTPException(503,'Synthetic invalid binding'))
        self.assertEqual(self.transition_post(self.app(store),f,key)[0],503)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))

    def test_api_transition_projection_tamper_fail_closed(self):
        f,key=self.legacy_fixture(),'projection-'+uuid4().hex
        value=self.transition(f,key)
        for field,wrong in (('approval_transferred',True),('legacy_files_adopted',True),('target_id','wrong'),
                            ('first_request_sha256','0'*64),('reviewer_id',str(uuid4())),('request_key','changed-key')):
            bad=copy.deepcopy(value); bad['transition'][field]=wrong
            bad['canonical_transition_text']=json.dumps(bad['transition'])
            bad['transition_sha256']=sha256(bad['canonical_transition_text'].encode()).hexdigest()
            with self.assertRaises(HTTPException) as error: IsolatedPortalTransition.validate_transition(bad,f['case'],key)
            self.assertEqual(error.exception.status_code,503)
        bad=copy.deepcopy(value); bad['canonical_transition_text']='not JSON'
        with self.assertRaises(HTTPException): IsolatedPortalTransition.validate_transition(bad,f['case'])
        for field,wrong in (('decision','approved'),('dispatch_enabled',True),('is_current','true'),('action_id',str(uuid4()))):
            bad=copy.deepcopy(value); bad['new_request'][field]=wrong
            with self.assertRaises(HTTPException): IsolatedPortalTransition.validate_transition(bad,f['case'])

    def test_api_projection_error_hides_owner_form_instead_of_context_fallback(self):
        f,key=self.legacy_fixture(),'context-fault-'+uuid4().hex
        value=self.transition(f,key); fresh=self.new_fixture(f,value)
        app,headers,_=self.browser(f)
        store=self.review_store()
        store.provenance=lambda *args: (_ for _ in ()).throw(HTTPException(503,'Synthetic context fault'))
        status,body,_=call(self.app(store),self.detail(fresh),headers=headers)
        self.assertEqual(status,503); self.assertNotIn(b'Approve exact portal request',body)
        self.assertEqual(self.bundle_count(value['transition']['first_request_id']),(0,0,0))

    def test_api_legacy_projection_tamper_fail_closed(self):
        f=self.legacy_fixture(); self.transition(f,'old-projection-'+uuid4().hex)
        value=self.review_store().legacy(f['session'],f['case'],f['old'])
        for field,wrong in (('case_id',str(uuid4())),('reviewer_id',str(uuid4())),('report_payload_sha256','0'*64)):
            bad=copy.deepcopy(value); bad['legacy_request']['request'][field]=wrong
            canonical=json.dumps(bad['legacy_request']['request'])
            bad['legacy_request']['canonical_payload_text']=canonical
            bad['legacy_request']['request_sha256']=sha256(canonical.encode()).hexdigest()
            with self.assertRaises(HTTPException): IsolatedPortalTransition.validate_legacy(bad,f['case'],f['old'])

    def test_api_owner_boundary_no_bearer_cross_origin_post_or_download(self):
        f=self.legacy_fixture(); self.transition(f,'owner-boundary-'+uuid4().hex)
        app,headers,_=self.browser(f)
        for path in (self.path_evidence(f),self.path_legacy(f)):
            self.assertEqual(call(app,path,headers=self.service_headers('service-'+uuid4().hex))[0],400)
            self.assertEqual(call(app,path,headers=headers+[(b'origin',b'https://evil.invalid')])[0],403)
            self.assertEqual(call(app,path,method='POST',headers=headers+[(b'origin',b'http://127.0.0.1:18081')])[0],405)
            self.assertEqual(call(app,path+'/export',headers=headers)[0],404)

    def test_api_expired_session_cannot_read_evidence_or_history(self):
        f=self.legacy_fixture(); self.transition(f,'expired-session-'+uuid4().hex)
        app,headers,_=self.browser(f,expired=True)
        for path in (self.path_evidence(f),self.path_legacy(f)):
            self.assertEqual(call(app,path,headers=headers)[0],303)

    def test_api_expired_first_request_successor_preserves_transition_context(self):
        f,key=self.legacy_fixture(seconds=-86401),'successor-context-'+uuid4().hex
        value=self.short_transition(f,key,seconds=-1)
        app,headers,_=self.browser(f)
        fresh=self.new_fixture(f,value)
        body=call(app,self.detail(fresh),headers=headers)[1]
        self.assertIn(b'Legacy target retired',body); self.assertNotIn(b'Approve exact portal request',body)
        payload={'report_revision':1,'report_payload_sha256':f['report_hash'],'predecessor_request_id':value['transition']['first_request_id']}
        status,body,_=self.issue(app,f['case'],payload)
        self.assertEqual(status,200)
        successor=dict(f,snapshot=json.loads(body))
        body=call(app,self.detail(successor),headers=headers)[1]
        self.assertIn(value['transition_sha256'].encode(),body)
        self.assertIn(value['transition']['first_request_sha256'].encode(),body)
        self.assertIn(b'Approve exact portal request',body)
        self.assertEqual(json.loads(self.transition_get(app,f,key)[1])['transition'],value['transition'])

    def test_api_clean_form_regression_and_old_hash_never_authorizes_new(self):
        clean=self.fixture_portal(); app,headers,_=self.browser(clean)
        self.assertEqual(self.post(app,clean,headers,self.form(app,clean,headers))[0],303)
        f=self.legacy_fixture(); value=self.transition(f,'reject-old-hash-'+uuid4().hex)
        fresh=self.new_fixture(f,value); app,headers,_=self.browser(fresh)
        form=self.form(app,fresh,headers)
        self.assertEqual(self.post(app,fresh,headers,dict(form,proposal_sha256=f['old_hash']))[0],409)
        self.assertEqual(self.bundle_count(value['transition']['first_request_id']),(0,0,0))

    def test_api_zz_revoked_owner_denies_state_transition_history_and_review(self):
        f,key=self.legacy_fixture(),'revoked-api-'+uuid4().hex
        value=self.transition(f,key); app,headers,_=self.browser(f)
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s',(self.owner,)); self.admin.commit()
        self.assertEqual(self.transition_get(app,f,key)[0],401)
        self.assertEqual(self.transition_post(app,f,key)[0],401)
        for path in (self.path_evidence(f),self.path_legacy(f),self.detail(self.new_fixture(f,value))):
            self.assertEqual(call(app,path,headers=headers)[0],303)


if __name__=='__main__':
    foundation.CONFIG=json.loads(sys.stdin.read())
    TransitionAPITests.__unittest_skip__=False
    suite=unittest.TestSuite(TransitionAPITests(name) for name in dir(TransitionAPITests) if name.startswith('test_api_'))
    class PrivateResult(unittest.TextTestResult):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.error_types,self.sqlstates,self.constraints=[],[],[]
        def addError(self,test,error):
            self.error_types.append(error[0].__name__)
            self.sqlstates.append(getattr(error[1],'sqlstate',None) or 'none')
            name=getattr(getattr(error[1],'diag',None),'constraint_name',None)
            self.constraints.append(name if isinstance(name,str) and re.fullmatch(r'[a-z0-9_]{1,128}',name) else 'none')
            super().addError(test,error)
    result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=PrivateResult).run(suite)
    print(json.dumps({'passed':result.wasSuccessful(),'tests_run':result.testsRun,
        'failed_tests':[getattr(t,'_testMethodName','class_setup') for t,_ in result.errors+result.failures],
        'error_types':result.error_types,'sqlstates':result.sqlstates,'constraints':result.constraints}))
