"""Private real-SQL/in-process ASGI tests, not listening HTTP/n8n evidence."""
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
from fastapi import FastAPI, HTTPException
from api.portal_attempts import IsolatedAttemptWorker, IsolatedAttemptRecovery, install_isolated_attempt_surfaces, install_isolated_attempt_worker
from api.portal_publication import IsolatedPortalPublicationStore
from test_wp4_portal_attempts_database import AttemptTests
from test_wp4_portal_publication_reads_database import CommitFault
from test_wp4_portal import call
import test_wp4_dispatch_database as foundation


@unittest.skipUnless(foundation.CONFIG is not None,'Private isolated database input required')
class AttemptApiTests(AttemptTests):
    def adapter(self,factory=None):
        return IsolatedAttemptWorker(self.store('attempt_worker',factory))

    def recovery_adapter(self,factory=None):
        return IsolatedAttemptRecovery(self.store('recovery',factory))

    def apps(self,worker=None,recovery=None):
        a,b=FastAPI(),FastAPI()
        install_isolated_attempt_surfaces(a,b,worker or self.adapter(),recovery or self.recovery_adapter(),
            foundation.CONFIG['attempt_token'],foundation.CONFIG['recovery_token'])
        return a,b

    def http(self,app,f,op=None,payload=None,operator=False,headers=None,body=None,query=b'',chunks=None):
        token=foundation.CONFIG['recovery_token' if operator else 'attempt_token']
        h=[(b'authorization',b'Bearer '+token.encode()),(b'idempotency-key',f['key'].encode())]
        if op: h.append((b'content-type',b'application/json'))
        return call(app,'/api/v4/portal-actions/'+f['action']+('/'+op if op else ''),'POST' if op else 'GET',
            json.dumps(payload if payload is not None else {}).encode() if body is None else body,
            h if headers is None else headers,query=query,chunks=chunks)

    def reserve_payload(self,f,execution='100',key=None):
        return dict(self.payload(f),attempt_key=key or 'api-attempt-'+uuid4().hex,execution_id=execution)

    def test_attempt_api_00_worker_only_installer_has_no_operator_or_recovery_secret(self):
        app=FastAPI(); worker=self.adapter()
        install_isolated_attempt_worker(app,worker,foundation.CONFIG['attempt_token'])
        f=self.approved()
        self.assertEqual(self.http(app,f)[0],200)
        self.assertEqual(self.http(app,f,'recover',{'recovery_key':'forbidden-key'})[0],404)
        self.assertEqual(self.http(app,f,headers=[(b'authorization',b'Bearer '+foundation.CONFIG['recovery_token'].encode())])[0],401)
        with self.assertRaises(ValueError):install_isolated_attempt_worker(FastAPI(),self.recovery_adapter(),foundation.CONFIG['attempt_token'])
        with self.assertRaises(ValueError):install_isolated_attempt_worker(FastAPI(),worker,'bad')

    @staticmethod
    def accept_payload(value):
        r=value['ledger']; return {'attempt_id':r['attempt_id'],'execution_id':r['execution_id']}

    def http_reserve(self,app,f,payload=None):
        status,body,_=self.http(app,f,'reserve',payload or self.reserve_payload(f))
        self.assertEqual(status,200); return json.loads(body)

    def test_attempt_api_01_full_cycle_ten_replays_and_get_never_grants(self):
        f=self.approved(); app,_=self.apps(); p=self.reserve_payload(f)
        before=json.loads(self.http(app,f)[1]); self.assertEqual(before['ledger']['state'],'pending')
        self.assertFalse(before['acceptance_permitted']); self.assertFalse(before['ledger']['reconciliation_required'])
        r=self.http_reserve(app,f,p); self.assertTrue(r['reservation_acknowledged']); self.assertTrue(r['acceptance_permitted'])
        for _ in range(10): self.assertEqual(self.http_reserve(app,f,p)['ledger']['attempt_id'],r['ledger']['attempt_id'])
        read=json.loads(self.http(app,f)[1]); self.assertFalse(read['acceptance_permitted']); self.assertEqual(self.event_count(f),1)
        token=self.accept_payload(r)
        for _ in range(10): self.assertEqual(self.http(app,f,'accept',token)[0],200)
        final=json.loads(self.http(app,f)[1]); self.assertEqual(final['ledger']['state'],'published')
        self.assertIsNotNone(final['worker']['receipt']); self.assertEqual(self.counts(f),(1,1)); self.assertEqual(self.event_count(f),2)

    def test_attempt_api_02_auth_precedes_body_and_credentials_are_separate(self):
        f=self.approved(); app,operator=self.apps()
        for other in ('owner_token','service_token','worker_token','recovery_token'):
            self.assertEqual(self.http(app,f,'reserve',headers=[(b'authorization',b'Bearer '+foundation.CONFIG[other].encode())],body=b'x'*9000)[0],401)
        self.assertEqual(self.http(operator,f,'recover',{'recovery_key':'operator-key-123'},headers=[(b'authorization',b'Bearer '+foundation.CONFIG['attempt_token'].encode())])[0],401)
        self.assertEqual(self.http(app,f,'recover',{'recovery_key':'operator-key-123'})[0],404)
        self.assertEqual(self.http(operator,f,'accept',{'attempt_id':str(uuid4()),'execution_id':'100'},operator=True)[0],404)
        self.assertEqual(self.event_count(f),0)

    def test_attempt_api_03_exact_reserve_payload_no_target_ttl_timestamp_or_sql(self):
        f=self.approved(); app,_=self.apps(); p=self.reserve_payload(f)
        for added in ('target_id','ttl','accepted_at','sql','url','reviewer_id','max_attempts'):
            self.assertEqual(self.http(app,f,'reserve',dict(p,**{added:'forbidden'}))[0],422)
        for field,bad in (('execution_id',1),('execution_id','0'),('attempt_key','short'),('case_id','bad'),('report_sha256','bad')):
            self.assertEqual(self.http(app,f,'reserve',dict(p,**{field:bad}))[0],422)
        self.assertEqual(self.event_count(f),0)

    def test_attempt_api_04_duplicate_json_body_bounds_headers_and_private_errors(self):
        f=self.approved(); app,_=self.apps()
        for body,status in ((b'{"execution_id":"1","execution_id":"2"}',422),(b'['*1100+b']'*1100,422),(b'x'*8193,413)):
            response=self.http(app,f,'reserve',body=body); self.assertEqual(response[0],status)
            self.assertEqual(dict(response[2])[b'cache-control'],b'no-store')
        token=foundation.CONFIG['attempt_token'].encode()
        headers=[(b'authorization',b'Bearer '+token),(b'authorization',b'Bearer '+token)]
        response=self.http(app,f,'reserve',headers=headers,body=b'x'*9000); self.assertEqual(response[0],401)
        self.assertEqual(dict(response[2])[b'cache-control'],b'no-store'); self.assertNotIn(token,response[1])
        good=[(b'authorization',b'Bearer '+token),(b'idempotency-key',f['key'].encode()),(b'idempotency-key',b'other-key-123'),(b'content-type',b'application/json')]
        self.assertEqual(self.http(app,f,'reserve',headers=good)[0],422); self.assertEqual(self.event_count(f),0)

    def test_attempt_api_05_browser_query_and_content_type_denied(self):
        f=self.approved(); app,_=self.apps(); p=self.reserve_payload(f)
        headers=[(b'authorization',b'Bearer '+foundation.CONFIG['attempt_token'].encode()),(b'idempotency-key',f['key'].encode()),(b'content-type',b'application/json')]
        for extra in ((b'cookie',b'x=y'),(b'origin',b'http://127.0.0.1:18081')):
            self.assertEqual(self.http(app,f,'reserve',p,headers=headers+[extra])[0],400)
        self.assertEqual(self.http(app,f,query=b'url=http://external')[0],400)
        self.assertEqual(self.http(app,f,'reserve',p,headers=headers[:-1]+[(b'content-type',b'text/plain')])[0],422)
        self.assertEqual(self.event_count(f),0)

    def test_attempt_api_06_missing_wrong_bindings_and_changed_original_key(self):
        f=self.approved(); app,_=self.apps(); p=self.reserve_payload(f)
        self.assertEqual(self.http(app,dict(f,action=str(uuid4())))[0],404)
        self.assertEqual(self.http(app,dict(f,action='BAD'))[0],422)
        for field,bad in (('case_id',str(uuid4())),('request_sha256','0'*64),('report_sha256','0'*64)):
            self.assertEqual(self.http(app,f,'reserve',dict(p,**{field:bad}))[0],409)
        self.http_reserve(app,f,p)
        self.assertEqual(self.http(app,dict(f,key='changed-original-123'))[0],409)
        self.assertEqual(self.counts(f),(0,0)); self.assertEqual(self.event_count(f),1)

    def test_attempt_api_07_other_execution_or_attempt_key_cannot_get_live_grant(self):
        f=self.approved(); app,_=self.apps(); p=self.reserve_payload(f); self.http_reserve(app,f,p)
        for changed in (dict(p,execution_id='101'),dict(p,attempt_key='other-attempt-123')):
            self.assertEqual(self.http(app,f,'reserve',changed)[0],409)
        self.assertEqual(self.event_count(f),1); self.assertEqual(self.state(f)['execution_id'],'100')

    def test_attempt_api_08_reservation_precommit_ack_failure_no_grant_no_slot(self):
        f=self.approved(); worker=self.adapter(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['attempt_worker']),False))
        app,_=self.apps(worker); p=self.reserve_payload(f)
        status,body,_=self.http(app,f,'reserve',p); self.assertEqual(status,503)
        self.assertNotIn(b'attempt_id',body); self.assertEqual(self.event_count(f),0)
        self.assertFalse(json.loads(self.http(self.apps()[0],f)[1])['acceptance_permitted'])

    def test_attempt_api_09_real_reservation_commit_simulated_ack_loss_same_key_recovers(self):
        f=self.approved(); worker=self.adapter(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['attempt_worker']),True))
        bad,_=self.apps(worker); p=self.reserve_payload(f)
        self.assertEqual(self.http(bad,f,'reserve',p)[0],503); self.assertEqual(self.event_count(f),1)
        good,_=self.apps(); read=json.loads(self.http(good,f)[1]); self.assertFalse(read['acceptance_permitted'])
        r=self.http_reserve(good,f,p); self.assertTrue(r['reservation_acknowledged']); self.assertEqual(r['ledger']['attempt_count'],1)
        self.assertEqual(self.http(good,f,'accept',self.accept_payload(r))[0],200); self.assertEqual(self.counts(f),(1,1))

    def test_attempt_api_10_accept_precommit_ack_failure_then_unknown_reconcile_new_slot(self):
        f=self.approved(); app,_=self.apps(); r=self.http_reserve(app,f); token=self.accept_payload(r)
        worker=self.adapter(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['attempt_worker']),False)); bad,_=self.apps(worker)
        self.assertEqual(self.http(bad,f,'accept',token)[0],503); self.assertEqual(self.counts(f),(0,0))
        self.assertEqual(self.http(app,f,'report',dict(token,outcome='uncertain'))[0],200)
        self.assertEqual(json.loads(self.http(app,f,'reconcile',{})[1])['ledger']['state'],'retryable')
        fresh=self.http_reserve(app,f,self.reserve_payload(f,'101')); self.assertEqual(fresh['ledger']['attempt_count'],2)
        self.assertEqual(self.http(app,f,'accept',token)[0],409)
        self.assertEqual(self.http(app,f,'accept',self.accept_payload(fresh))[0],200); self.assertEqual(self.counts(f),(1,1))

    def test_attempt_api_11_real_accept_commit_simulated_ack_loss_no_second_effect(self):
        f=self.approved(); app,_=self.apps(); r=self.http_reserve(app,f); token=self.accept_payload(r)
        worker=self.adapter(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['attempt_worker']),True)); bad,_=self.apps(worker)
        status,body,_=self.http(bad,f,'accept',token); self.assertEqual(status,503); self.assertNotIn(b'publication_id',body)
        self.assertEqual(self.counts(f),(1,1)); fresh,_=self.apps()
        self.assertEqual(json.loads(self.http(fresh,f,'reconcile',{})[1])['ledger']['state'],'published')
        self.assertEqual(self.http(fresh,f,'accept',token)[0],200); self.assertEqual(self.event_count(f),2)

    def test_attempt_api_12_reserved_return_tamper_rolls_back_before_grant(self):
        f=self.approved(); worker=self.adapter(); actual=worker.validate
        for field,bad in (('attempt_count',True),('max_attempts',4),('event_no',0),('reconciliation_required',False),('attempt_key','bad')):
            def tamper(value,*args,field=field,bad=bad,**kwargs):
                value=copy.deepcopy(value); value['ledger'][field]=bad; return actual(value,*args,**kwargs)
            with patch.object(worker,'validate',side_effect=tamper):
                self.assertEqual(self.http(self.apps(worker)[0],f,'reserve',self.reserve_payload(f))[0],503)
            self.assertEqual(self.event_count(f),0)

    def test_attempt_api_13_receipt_tamper_rolls_back_before_publication_response(self):
        f=self.approved(); app,_=self.apps(); r=self.http_reserve(app,f); worker=self.adapter(); actual=worker.validate
        def tamper(value,*args,**kwargs):
            value=copy.deepcopy(value); value['worker']['snapshot']['request_sha256']='0'*64; return actual(value,*args,**kwargs)
        with patch.object(worker,'validate',side_effect=tamper):
            self.assertEqual(self.http(self.apps(worker)[0],f,'accept',self.accept_payload(r))[0],503)
        self.assertEqual(self.counts(f),(0,0)); self.assertEqual(self.event_count(f),1)

    def test_attempt_api_14_fresh_adapters_preserve_three_slot_exhaustion(self):
        f=self.approved()
        for n in range(1,4):
            app,_=self.apps(); r=self.http_reserve(app,f,self.reserve_payload(f,str(100+n)))
            response=json.loads(self.http(app,f,'report',dict(self.accept_payload(r),outcome='retryable'))[1])
            self.assertEqual(response['ledger']['state'],'retryable' if n<3 else 'exhausted')
        app,operator=self.apps(); r=self.http_reserve(app,f,self.reserve_payload(f,'999'))
        self.assertEqual(r['ledger']['attempt_count'],3); self.assertFalse(r['acceptance_permitted'])
        recovered=json.loads(self.http(operator,f,'recover',{'recovery_key':'operator-exhaustion-123'},operator=True)[1])
        self.assertEqual(recovered['ledger']['state'],'exhausted'); self.assertEqual(self.counts(f),(0,0))

    def test_attempt_api_15_operator_unknown_recovery_no_approval_or_budget_reset(self):
        f=self.approved(); app,operator=self.apps(); r=self.http_reserve(app,f); token=self.accept_payload(r)
        self.http(app,f,'report',dict(token,outcome='uncertain'))
        self.assertEqual(self.http_reserve(app,f,self.reserve_payload(f,'101'))['ledger']['state'],'unknown')
        p={'recovery_key':'operator-unknown-123'}
        for _ in range(10):
            response=self.http(operator,f,'recover',p,operator=True); self.assertEqual(response[0],200)
            self.assertFalse(json.loads(response[1])['acceptance_permitted'])
        self.assertEqual(self.event_count(f),3); self.assertEqual(self.state(f)['attempt_count'],1)
        self.assertEqual(self.http(app,f,'accept',token)[0],409)
        fresh=self.http_reserve(app,f,self.reserve_payload(f,'101')); self.assertEqual(fresh['ledger']['attempt_count'],2)

    def test_attempt_api_16_permanent_dead_letter_no_worker_or_operator_reopen(self):
        f=self.approved(); app,operator=self.apps(); r=self.http_reserve(app,f)
        response=self.http(app,f,'report',dict(self.accept_payload(r),outcome='permanent')); self.assertEqual(response[0],200)
        self.assertEqual(json.loads(response[1])['ledger']['state'],'dead_letter')
        recovered=self.http(operator,f,'recover',{'recovery_key':'operator-permanent-123'},operator=True)
        self.assertEqual(json.loads(recovered[1])['ledger']['state'],'dead_letter')
        self.assertFalse(self.http_reserve(app,f,self.reserve_payload(f,'101'))['acceptance_permitted'])
        self.assertEqual(self.counts(f),(0,0))

    def test_attempt_api_17_actual_expiry_live_recovery_denial_and_no_new_request(self):
        f=self.approved(seconds=1.2); app,operator=self.apps(); r=self.http_reserve(app,f)
        self.assertEqual(self.http(operator,f,'recover',{'recovery_key':'operator-live-123'},operator=True)[0],409)
        self.wait_expired(f['saved']['request']['proposal_id'])
        self.assertEqual(self.http(app,f,'accept',self.accept_payload(r))[0],409)
        response=self.http(app,f,'reconcile',{}); self.assertEqual(response[0],200)
        self.assertEqual(json.loads(response[1])['ledger']['state'],'expired'); self.assertEqual(self.counts(f),(0,0))

    def test_attempt_api_18_published_read_replay_after_original_deadline(self):
        f=self.approved(seconds=1.2); app,_=self.apps(); r=self.http_reserve(app,f)
        self.assertEqual(self.http(app,f,'accept',self.accept_payload(r))[0],200)
        self.wait_expired(f['saved']['request']['proposal_id'])
        response=self.http(app,f); self.assertEqual(response[0],200); self.assertEqual(json.loads(response[1])['ledger']['state'],'published')
        self.assertEqual(self.http(app,f,'accept',self.accept_payload(r))[0],200); self.assertEqual(self.counts(f),(1,1))

    def test_attempt_api_19_held_writer_is_busy_not_false_pending(self):
        f=self.approved(); app,operator=self.apps(); r=self.http_reserve(app,f)
        with self.connect('attempt_worker') as conn:
            self.accept(f,r['ledger'],conn)
            for response in (self.http(app,f),self.http(operator,f,'recover',{'recovery_key':'operator-held-123'},operator=True)):
                self.assertEqual(response[0],429); self.assertEqual(dict(response[2])[b'retry-after'],b'5')
            self.assertEqual(self.counts(f),(0,0)); conn.rollback()
        self.assertEqual(self.event_count(f),1)

    def test_attempt_api_20_connection_admission_autocommit_and_slot_guard(self):
        f=self.approved(); worker=self.adapter(); app,_=self.apps(worker)
        worker.store.slot.acquire()
        try:
            with patch.object(worker.store,'factory',side_effect=AssertionError('Must not connect')):
                self.assertEqual(self.http(app,f)[0],429)
        finally: worker.store.slot.release()
        def auto(): return psycopg.connect(**foundation.CONFIG['attempt_worker'],autocommit=True)
        self.assertEqual(self.http(self.apps(self.adapter(auto))[0],f)[0],503)
        wrong=lambda:psycopg.connect(**foundation.CONFIG['worker'])
        self.assertEqual(self.http(self.apps(self.adapter(wrong))[0],f)[0],503)
        with self.assertRaises(ValueError): IsolatedPortalPublicationStore(lambda:None,'raa_wp2_validation',foundation.CONFIG['attempt_worker']['user'])
        self.assertEqual(self.event_count(f),0)

    def test_attempt_api_21_separate_installation_and_no_arbitrary_report_fields(self):
        f=self.approved(); worker,recovery=self.adapter(),self.recovery_adapter(); a,b=FastAPI(),FastAPI()
        with self.assertRaises(ValueError): install_isolated_attempt_surfaces(a,b,worker,recovery,'a'*64,'a'*64)
        with self.assertRaises(ValueError): install_isolated_attempt_surfaces(a,a,worker,recovery,'a'*64,'b'*64)
        app,operator=self.apps(); r=self.http_reserve(app,f); token=self.accept_payload(r)
        for p in (dict(token,outcome='published'),dict(token,outcome='uncertain',error='token'),dict(token,outcome=[])):
            self.assertEqual(self.http(app,f,'report',p)[0],422)
        self.assertEqual(self.http(app,f,'reconcile',{'renew':True})[0],422)
        self.assertEqual(self.http(operator,f,'recover',{'recovery_key':'operator-key-123','reset':True},operator=True)[0],422)
        self.assertEqual(self.event_count(f),1)

    def test_attempt_api_22_deferred_actual_commit_fault_no_candidate_response(self):
        f=self.approved(); app,_=self.apps(); r=self.http_reserve(app,f)
        self.admin.execute("CREATE FUNCTION pg_temp.api_attempt_commit_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF NEW.kind='accepted' THEN RAISE EXCEPTION 'Synthetic commit failure'; END IF; RETURN NEW; END $$")
        self.admin.execute('CREATE CONSTRAINT TRIGGER attempt_api_fault AFTER INSERT ON retail.portal_worker_events_v1 '
            'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION pg_temp.api_attempt_commit_fault()'); self.admin.commit()
        try:
            status,body,_=self.http(app,f,'accept',self.accept_payload(r)); self.assertEqual(status,503); self.assertNotIn(b'publication_id',body)
            self.assertEqual(self.counts(f),(0,0)); self.assertEqual(self.event_count(f),1)
        finally:
            self.admin.execute('DROP TRIGGER attempt_api_fault ON retail.portal_worker_events_v1'); self.admin.commit()

    def test_attempt_api_23_two_concurrent_api_accepts_single_effect(self):
        f=self.approved(); app,_=self.apps(); r=self.http_reserve(app,f); token=self.accept_payload(r)
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(lambda _:self.http(self.apps()[0],f,'accept',token)[0],range(2)))
        self.assertTrue(all(s in (200,429) for s in results)); self.assertIn(200,results)
        self.assertEqual(self.counts(f),(1,1)); self.assertEqual(self.event_count(f),2)

    def test_attempt_api_24_report_before_after_commit_ack_failure_reconciles_state(self):
        for after in (False,True):
            f=self.approved(); app,_=self.apps(); r=self.http_reserve(app,f); token=self.accept_payload(r)
            worker=self.adapter(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['attempt_worker']),after)); bad,_=self.apps(worker)
            status,body,_=self.http(bad,f,'report',dict(token,outcome='uncertain'))
            self.assertEqual(status,503); self.assertNotIn(b'attempt_id',body)
            self.assertEqual(self.state(f)['state'],'unknown' if after else 'reserved')
            self.assertEqual(self.event_count(f),2 if after else 1); self.assertEqual(self.counts(f),(0,0))

    def test_attempt_api_25_operator_before_after_commit_ack_failure_same_key_replay(self):
        for after in (False,True):
            f=self.approved(); app,operator=self.apps(); r=self.http_reserve(app,f)
            self.http(app,f,'report',dict(self.accept_payload(r),outcome='uncertain'))
            recovery=self.recovery_adapter(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['recovery']),after))
            _,bad=self.apps(recovery=recovery); p={'recovery_key':'operator-lost-ack-'+uuid4().hex}
            status,body,_=self.http(bad,f,'recover',p,operator=True); self.assertEqual(status,503); self.assertNotIn(b'attempt_id',body)
            self.assertEqual(self.event_count(f),3 if after else 2)
            self.assertEqual(self.http(operator,f,'recover',p,operator=True)[0],200)
            self.assertEqual(self.event_count(f),3); self.assertEqual(self.state(f)['attempt_count'],1)

    def test_attempt_api_26_reconciliation_after_commit_ack_failure_no_new_slot(self):
        f=self.approved(); app,_=self.apps(); r=self.http_reserve(app,f)
        self.http(app,f,'report',dict(self.accept_payload(r),outcome='uncertain'))
        worker=self.adapter(lambda:CommitFault(psycopg.connect(**foundation.CONFIG['attempt_worker']),True)); bad,_=self.apps(worker)
        self.assertEqual(self.http(bad,f,'reconcile',{})[0],503); self.assertEqual(self.state(f)['state'],'retryable')
        self.assertEqual(self.http(app,f,'reconcile',{})[0],200); self.assertEqual(self.event_count(f),3)
        self.assertEqual(self.state(f)['attempt_count'],1)

    def test_attempt_api_zz_revocation_denies_worker_and_operator(self):
        f=self.approved(); app,operator=self.apps(); r=self.http_reserve(app,f)
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s',(self.owner,)); self.admin.commit()
        for response in (self.http(app,f),self.http(app,f,'accept',self.accept_payload(r)),
                         self.http(operator,f,'recover',{'recovery_key':'operator-revoked-123'},operator=True)):
            self.assertEqual(response[0],401)
        self.assertEqual(self.counts(f),(0,0))


if __name__=='__main__':
    foundation.CONFIG=json.loads(sys.stdin.read()); AttemptApiTests.__unittest_skip__=False
    names=[n for n in dir(AttemptApiTests) if n.startswith('test_attempt_api_') and '_zz_' not in n]
    names += [n for n in dir(AttemptApiTests) if n.startswith('test_attempt_') and not n.startswith('test_attempt_api_') and '_zz_' not in n]
    names += [n for n in dir(AttemptApiTests) if n.startswith('test_portal_') and 'zz_' not in n]
    names += ['test_attempt_api_zz_revocation_denies_worker_and_operator']
    class PrivateResult(unittest.TextTestResult):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw); self.error_types=[]; self.sqlstates=[]; self.constraints=[]
        def addError(self,t,e):
            self.error_types.append(e[0].__name__); self.sqlstates.append(getattr(e[1],'sqlstate',None) or 'none')
            name=getattr(getattr(e[1],'diag',None),'constraint_name',None)
            self.constraints.append(name if isinstance(name,str) and re.fullmatch(r'[a-z0-9_]{1,128}',name) else 'none'); super().addError(t,e)
    r=unittest.TextTestRunner(stream=io.StringIO(),resultclass=PrivateResult).run(unittest.TestSuite(AttemptApiTests(n) for n in names))
    print(json.dumps({'passed':r.wasSuccessful(),'tests_run':r.testsRun,'failed_tests':[getattr(t,'_testMethodName','setup') for t,_ in r.errors+r.failures],
                     'error_types':r.error_types,'sqlstates':r.sqlstates,'constraints':r.constraints}))
