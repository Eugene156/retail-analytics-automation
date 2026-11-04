"""Private durable worker SQL tests; no n8n/HTTP/main deployment."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import re
import subprocess
import sys
import threading
import time
import unittest
from uuid import uuid4

import psycopg
import test_wp4_dispatch_database as foundation
from test_wp4_portal_worker_database import WorkerTests


@unittest.skipUnless(foundation.CONFIG is not None,'Private isolated database input required')
class AttemptTests(WorkerTests):
    def query(self,name,args,kind='attempt_worker',conn=None):
        sql='SELECT retail.'+name+'('+','.join(['%s']*len(args))+')'
        if conn is not None:
            return json.loads(conn.execute(sql,args).fetchone()[0])
        with self.connect(kind) as connection:
            return json.loads(connection.execute(sql,args).fetchone()[0])

    def state(self,f):
        return self.query('api_portal_attempt_state_v1',(f['action'],f['key']))['ledger']

    def reserve(self,f,execution='100',attempt_key=None,conn=None,payload=None):
        p=payload or self.payload(f)
        return self.query('api_reserve_portal_attempt_v1',(f['action'],f['key'],p['case_id'],p['request_sha256'],
            p['report_sha256'],attempt_key or 'attempt-'+uuid4().hex,execution),conn=conn)['ledger']

    def accept(self,f,r,conn=None):
        return self.query('api_accept_portal_attempt_v1',(f['action'],f['key'],r['attempt_id'],r['execution_id']),conn=conn)['ledger']

    def report(self,f,r,outcome):
        return self.query('api_report_portal_attempt_v1',(f['action'],f['key'],r['attempt_id'],r['execution_id'],outcome))['ledger']

    def reconcile(self,f):
        return self.query('api_reconcile_portal_attempt_v1',(f['action'],f['key']))['ledger']

    def recover(self,f,key=None):
        return self.query('api_operator_reconcile_portal_v1',(f['action'],f['key'],key or 'recovery-'+uuid4().hex),'recovery')['ledger']

    def event_count(self,f):
        n=self.admin.execute('SELECT count(*) FROM retail.portal_worker_events_v1 WHERE action_id=%s',(f['action'],)).fetchone()[0]
        self.admin.rollback(); return n

    def test_attempt_01_actual_scoped_roles_no_bypass_or_tables(self):
        for kind,number in (('attempt_worker',5),('recovery',1)):
            with psycopg.connect(**foundation.CONFIG[kind]) as conn:
                self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0],'on')
                self.assertEqual(conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='retail' AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')").fetchone()[0],number)
                for tab in ('portal_worker_events_v1','portal_publications_v2','owner_credentials'):
                    self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE,DELETE')",('retail.'+tab,)).fetchone()[0])
                for fn in ('api_worker_accept_portal_v2(uuid,text,uuid,text,text)','api_accept_portal_publication_v2(uuid,text)',
                           'portal_append_attempt_event_v1(uuid,text,text,text,text,text)','api_decide_portal_request_v2(text,text,uuid,text,text,text)'):
                    self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')",('retail.'+fn,)).fetchone()[0])
                if kind=='attempt_worker':
                    self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,'retail.api_operator_reconcile_portal_v1(uuid,text,text)','EXECUTE')").fetchone()[0])
                else:
                    self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,'retail.api_accept_portal_attempt_v1(uuid,text,uuid,text)','EXECUTE')").fetchone()[0])
        self.assertEqual(self.admin.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('raa_wp4_portal_attempt_v1','raa_wp4_portal_recovery_v1') AND NOT rolcanlogin").fetchone()[0],2)
        self.admin.rollback()

    def test_attempt_02_committed_reservation_success_and_ten_replays(self):
        f=self.approved(); key='reservation-'+uuid4().hex
        r=self.reserve(f,attempt_key=key); self.assertEqual(r['state'],'reserved'); self.assertEqual(self.counts(f),(0,0))
        for _ in range(10): self.assertEqual(self.reserve(f,attempt_key=key)['attempt_id'],r['attempt_id'])
        self.assertEqual(self.event_count(f),1)
        accepted=self.accept(f,r); self.assertEqual(accepted['state'],'published')
        for _ in range(10): self.assertEqual(self.accept(f,r)['state'],'published')
        self.assertEqual(self.event_count(f),2); self.assertEqual(self.counts(f),(1,1))
        self.assertEqual(self.reserve(f,execution='101')['attempt_count'],1)

    def test_attempt_03_reservation_must_commit_even_inside_subtransaction(self):
        f=self.approved()
        with self.connect('attempt_worker') as conn:
            with conn.transaction(): r=self.reserve(f,conn=conn)
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept(f,r,conn)
            conn.rollback()
        self.assertEqual(self.event_count(f),0); self.assertEqual(self.counts(f),(0,0))

    def test_attempt_04_new_execution_cannot_reset_three_attempt_budget(self):
        f=self.approved()
        for n in range(1,4):
            r=self.reserve(f,execution=str(100+n)); self.assertEqual(r['attempt_count'],n)
            closed=self.report(f,r,'retryable'); self.assertEqual(closed['state'],'retryable' if n<3 else 'exhausted')
        self.assertEqual(self.reserve(f,execution='999')['state'],'exhausted')
        self.assertEqual(self.recover(f)['state'],'exhausted')
        self.assertEqual(self.reserve(f,execution='1000')['attempt_count'],3)
        self.assertEqual(self.event_count(f),7); self.assertEqual(self.counts(f),(0,0))

    def test_attempt_05_unknown_requires_reconciliation_fences_stale_accept(self):
        f=self.approved(); r=self.reserve(f)
        self.assertEqual(self.report(f,r,'uncertain')['state'],'unknown')
        self.assertEqual(self.reserve(f,execution='101')['state'],'unknown')
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept(f,r)
        self.assertEqual(self.reconcile(f)['state'],'retryable')
        later=self.reserve(f,execution='101'); self.assertEqual(later['attempt_count'],2)
        for method in (lambda:self.accept(f,r),lambda:self.report(f,r,'permanent')):
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): method()
        self.assertEqual(self.accept(f,later)['state'],'published'); self.assertEqual(self.counts(f),(1,1))

    def test_attempt_06_live_reservation_cannot_be_stolen_or_recovered(self):
        f=self.approved(); r=self.reserve(f)
        self.assertEqual(self.reserve(f,execution='101')['attempt_id'],r['attempt_id'])
        for method in (lambda:self.reconcile(f),lambda:self.recover(f)):
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): method()
        self.assertEqual(self.event_count(f),1)

    def test_attempt_07_permanent_dead_letter_operator_cannot_reset(self):
        f=self.approved(); r=self.reserve(f)
        self.assertEqual(self.report(f,r,'permanent')['state'],'dead_letter')
        self.assertEqual(self.recover(f)['state'],'dead_letter')
        self.assertEqual(self.reserve(f,execution='101')['state'],'dead_letter')
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept(f,r)
        self.assertEqual(self.counts(f),(0,0))

    def test_attempt_08_original_key_execution_and_hash_bound_before_effect(self):
        f=self.approved(); r=self.reserve(f,attempt_key='bound-key-123')
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.reserve(f,execution='101',attempt_key='bound-key-123')
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.state(dict(f,key='other-business-key'))
        for field,value in (('case_id',str(uuid4())),('request_sha256','0'*64),('report_sha256','0'*64)):
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.reserve(f,payload=dict(self.payload(f),**{field:value}))
        for changed in (dict(r,attempt_id=str(uuid4())),dict(r,execution_id='101')):
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept(f,changed)
        self.assertEqual(self.event_count(f),1); self.assertEqual(self.counts(f),(0,0))

    def test_attempt_09_expired_reservation_cannot_publish_or_renew(self):
        f=self.approved(seconds=1.2); r=self.reserve(f)
        self.wait_expired(f['saved']['request']['proposal_id'])
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept(f,r)
        self.assertEqual(self.reconcile(f)['state'],'expired')
        self.assertEqual(self.recover(f)['state'],'expired')
        self.assertEqual(self.reserve(f,execution='101')['attempt_count'],1)
        self.assertEqual(self.counts(f),(0,0))

    def test_attempt_10_accepted_replay_and_operator_read_after_request_expiry(self):
        f=self.approved(seconds=1.2); r=self.reserve(f); self.accept(f,r)
        self.wait_expired(f['saved']['request']['proposal_id'])
        self.assertEqual(self.accept(f,r)['state'],'published')
        self.assertEqual(self.recover(f)['state'],'published'); self.assertEqual(self.counts(f),(1,1))

    def test_attempt_11_event_fault_atomically_rolls_back_publication_not_reservation(self):
        f=self.approved(); r=self.reserve(f)
        self.admin.execute("CREATE FUNCTION pg_temp.attempt_event_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF NEW.kind='accepted' THEN RAISE EXCEPTION 'Synthetic event failure'; END IF; RETURN NEW; END $$")
        self.admin.execute('CREATE TRIGGER attempt_test_fault BEFORE INSERT ON retail.portal_worker_events_v1 FOR EACH ROW EXECUTE FUNCTION pg_temp.attempt_event_fault()'); self.admin.commit()
        try:
            with self.assertRaises(psycopg.errors.RaiseException): self.accept(f,r)
            self.assertEqual(self.counts(f),(0,0)); self.assertEqual(self.state(f)['attempt_count'],1)
        finally:
            self.admin.execute('DROP TRIGGER attempt_test_fault ON retail.portal_worker_events_v1'); self.admin.commit()
        self.assertEqual(self.accept(f,r)['state'],'published')

    def test_attempt_12_publication_audit_fault_preserves_durable_reservation(self):
        f=self.approved(); r=self.reserve(f)
        self.admin.execute("CREATE FUNCTION pg_temp.attempt_audit_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF NEW.kind='publication_accepted' THEN RAISE EXCEPTION 'Synthetic audit failure'; END IF; RETURN NEW; END $$")
        self.admin.execute('CREATE TRIGGER attempt_test_fault BEFORE INSERT ON retail.portal_publication_audit_v2 FOR EACH ROW EXECUTE FUNCTION pg_temp.attempt_audit_fault()'); self.admin.commit()
        try:
            with self.assertRaises(psycopg.errors.RaiseException): self.accept(f,r)
            self.assertEqual(self.counts(f),(0,0)); self.assertEqual(self.event_count(f),1)
        finally:
            self.admin.execute('DROP TRIGGER attempt_test_fault ON retail.portal_publication_audit_v2'); self.admin.commit()

    def test_attempt_13_two_concurrent_reservations_one_consumed_slot(self):
        f=self.approved(); barrier=threading.Barrier(2)
        def run(n):
            barrier.wait(timeout=5)
            try: return self.reserve(f,execution=str(100+n))
            except psycopg.errors.LockNotAvailable: return None
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(run,range(2)))
        self.assertTrue(any(r is not None for r in results)); self.assertEqual(self.event_count(f),1)
        r=self.state(f); self.assertEqual(r['attempt_count'],1); self.accept(f,r); self.assertEqual(self.counts(f),(1,1))

    def test_attempt_14_held_uncommitted_accept_blocks_recovery_and_rollback_preserves_slot(self):
        f=self.approved(); r=self.reserve(f)
        with self.connect('attempt_worker') as conn:
            self.accept(f,r,conn)
            with self.assertRaises(psycopg.errors.LockNotAvailable): self.recover(f)
            self.assertEqual(self.counts(f),(0,0)); conn.rollback()
        self.assertEqual(self.state(f)['state'],'reserved'); self.assertEqual(self.event_count(f),1)

    def test_attempt_15_events_immutable_direct_transition_tampering_denied(self):
        f=self.approved(); r=self.reserve(f)
        for sql in ("UPDATE retail.portal_worker_events_v1 SET attempt_no=1 WHERE action_id=%s",'DELETE FROM retail.portal_worker_events_v1 WHERE action_id=%s'):
            with self.assertRaises(psycopg.errors.RaiseException): self.admin.execute(sql,(f['action'],))
            self.admin.rollback()
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            self.admin.execute("INSERT INTO retail.portal_worker_events_v1 SELECT gen_random_uuid(),action_id,event_no+1,acceptance_key,attempt_id,"
                "reservation_xid,attempt_no,attempt_key,execution_id,'accepted','committed','published',clock_timestamp(),lease_expires_at,NULL,session_user "
                "FROM retail.portal_worker_events_v1 WHERE action_id=%s",(f['action'],))
        self.admin.rollback(); self.assertEqual(self.event_count(f),1)

    def test_attempt_16_bounded_input_and_report_replay_no_raw_error_text(self):
        f=self.approved(); r=self.reserve(f)
        for execution in ('0','-1','1.0','x'*30):
            with self.assertRaises(psycopg.errors.InvalidParameterValue): self.reserve(f,execution=execution)
        for outcome in ('published','error with token','unknown','',None):
            with self.assertRaises(psycopg.errors.InvalidParameterValue): self.report(f,r,outcome)
        self.report(f,r,'uncertain'); n=self.event_count(f)
        for _ in range(10): self.report(f,r,'uncertain')
        self.assertEqual(self.event_count(f),n)

    def test_attempt_17_operator_recovery_key_replay_and_cap(self):
        f=self.approved(); r=self.reserve(f); self.report(f,r,'uncertain')
        key='operator-replay-123'; self.recover(f,key); n=self.event_count(f)
        for _ in range(10): self.recover(f,key)
        self.assertEqual(self.event_count(f),n)
        for n in range(19): self.recover(f,'operator-cap-'+str(n))
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.recover(f,'operator-over-cap')
        self.assertEqual(self.state(f)['attempt_count'],1)
        actor=self.admin.execute("SELECT bool_and(actor_login=%s) FROM retail.portal_worker_events_v1 WHERE action_id=%s AND kind='operator_reconciled'",
            (foundation.CONFIG['recovery']['user'],f['action'])).fetchone()[0]
        self.admin.rollback(); self.assertTrue(actor)

    def test_attempt_18_expired_approved_successor_cannot_inherit_budget_or_decision(self):
        f=self.approved(seconds=1.2); r=self.reserve(f); self.wait_expired(f['saved']['request']['proposal_id'])
        with self.connect('issuer') as conn:
            successor=json.loads(conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                (f['case'],self.payload(f)['report_sha256'],'successor-'+uuid4().hex,f['saved']['request']['proposal_id'])).fetchone()[0])
        self.assertIsNone(successor['action_id']); self.assertIsNone(successor['decision'])
        self.assertEqual(self.reconcile(f)['state'],'superseded')
        fresh=dict(f,snapshot=successor); saved=self.decide_portal(fresh)
        newer=dict(fresh,saved=saved,action=saved['action_id'],key='newer-'+uuid4().hex)
        self.assertEqual(self.state(newer)['attempt_count'],0)
        self.accept(newer,self.reserve(newer)); self.assertEqual(self.counts(newer),(1,1))
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept(f,r)

    def crash(self,f,r,commit):
        code="""import json,os,sys,psycopg
p=json.loads(sys.stdin.read())
c=psycopg.connect(**p['config']); c.read_only=False
c.execute('SELECT retail.api_accept_portal_attempt_v1(%s,%s,%s,%s)',p['args']).fetchone()
if p['commit']: c.commit()
os._exit(23)
"""
        result=subprocess.run([sys.executable,'-c',code],input=json.dumps({'config':foundation.CONFIG['attempt_worker'],
            'args':[f['action'],f['key'],r['attempt_id'],r['execution_id']],'commit':commit}),text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,23)  # Never emit captured private stderr.

    def test_attempt_19_actual_process_exit_before_commit_lease_recovery_and_fenced_retry(self):
        f=self.approved(); r=self.reserve(f); self.crash(f,r,False)
        self.assertEqual(self.counts(f),(0,0)); self.assertEqual(self.event_count(f),1)
        remaining=self.admin.execute('SELECT greatest(0,extract(epoch FROM max(lease_expires_at)-clock_timestamp())) '
            'FROM retail.portal_worker_events_v1 WHERE action_id=%s',(f['action'],)).fetchone()[0]
        self.admin.rollback(); time.sleep(float(remaining)+0.08)
        self.assertEqual(self.state(f)['state'],'unknown')
        self.assertEqual(self.reserve(f,execution='101')['attempt_count'],1)
        self.assertEqual(self.reconcile(f)['state'],'retryable')
        next_attempt=self.reserve(f,execution='101'); self.assertEqual(next_attempt['attempt_count'],2)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept(f,r)
        self.assertEqual(self.accept(f,next_attempt)['state'],'published'); self.assertEqual(self.counts(f),(1,1))

    def test_attempt_20_actual_process_exit_after_commit_reconciles_without_new_effect(self):
        f=self.approved(); r=self.reserve(f); self.crash(f,r,True)
        self.assertEqual(self.reconcile(f)['state'],'published')
        self.assertEqual(self.recover(f)['state'],'published'); self.assertEqual(self.accept(f,r)['state'],'published')
        self.assertEqual(self.counts(f),(1,1)); self.assertEqual(self.state(f)['attempt_count'],1)

    def test_attempt_21_missing_legacy_or_unapproved_has_no_ledger(self):
        f=self.approved()
        for changed in (dict(f,action=str(uuid4())),dict(f,action=str(self.fixture()['action_id']))):
            with self.assertRaises(psycopg.errors.NoDataFound): self.state(changed)
            with self.assertRaises(psycopg.errors.NoDataFound): self.reserve(changed)
        self.assertEqual(self.event_count(f),0)
        unapproved=self.fixture_portal(); self.assertIsNone(unapproved['snapshot']['action_id'])

    def test_attempt_22_deferred_commit_fault_leaves_reservation_and_no_successful_effect(self):
        f=self.approved(); r=self.reserve(f)
        self.admin.execute("CREATE FUNCTION pg_temp.attempt_commit_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF NEW.kind='accepted' THEN RAISE EXCEPTION 'Synthetic deferred failure'; END IF; RETURN NEW; END $$")
        self.admin.execute('CREATE CONSTRAINT TRIGGER attempt_test_fault AFTER INSERT ON retail.portal_worker_events_v1 '
            'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION pg_temp.attempt_commit_fault()'); self.admin.commit()
        try:
            with self.connect('attempt_worker') as conn:
                self.assertEqual(self.accept(f,r,conn)['state'],'published')  # Candidate only, not committed receipt.
                with self.assertRaises(psycopg.errors.RaiseException): conn.commit()
                conn.rollback()
            self.assertEqual(self.counts(f),(0,0)); self.assertEqual(self.event_count(f),1)
        finally:
            self.admin.execute('DROP TRIGGER attempt_test_fault ON retail.portal_worker_events_v1'); self.admin.commit()

    def test_attempt_23_two_concurrent_accepts_same_reserved_attempt_single_effect(self):
        f=self.approved(); r=self.reserve(f); barrier=threading.Barrier(2)
        def run(_):
            barrier.wait(timeout=5)
            try: return self.accept(f,r)
            except psycopg.errors.LockNotAvailable: return None
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(run,range(2)))
        self.assertTrue(any(v is not None for v in results))
        self.assertEqual(self.accept(f,r)['state'],'published'); self.assertEqual(self.counts(f),(1,1)); self.assertEqual(self.event_count(f),2)

    def test_attempt_24_operator_event_fault_rolls_back_without_erasing_unknown(self):
        f=self.approved(); r=self.reserve(f); self.report(f,r,'uncertain')
        self.admin.execute("CREATE FUNCTION pg_temp.operator_event_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF NEW.kind='operator_reconciled' THEN RAISE EXCEPTION 'Synthetic recovery failure'; END IF; RETURN NEW; END $$")
        self.admin.execute('CREATE TRIGGER attempt_test_fault BEFORE INSERT ON retail.portal_worker_events_v1 '
            'FOR EACH ROW EXECUTE FUNCTION pg_temp.operator_event_fault()'); self.admin.commit()
        try:
            with self.assertRaises(psycopg.errors.RaiseException): self.recover(f)
            self.assertEqual(self.state(f)['state'],'unknown'); self.assertEqual(self.event_count(f),2)
        finally:
            self.admin.execute('DROP TRIGGER attempt_test_fault ON retail.portal_worker_events_v1'); self.admin.commit()
        self.assertEqual(self.recover(f)['state'],'retryable')

    def test_attempt_zz_owner_revocation_denies_all_worker_and_recovery_calls(self):
        f=self.approved(); r=self.reserve(f)
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s',(self.owner,)); self.admin.commit()
        for method in (lambda:self.state(f),lambda:self.reserve(f),lambda:self.accept(f,r),lambda:self.report(f,r,'uncertain'),lambda:self.reconcile(f),lambda:self.recover(f)):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): method()
        self.assertEqual(self.counts(f),(0,0))


if __name__=='__main__':
    foundation.CONFIG=json.loads(sys.stdin.read()); AttemptTests.__unittest_skip__=False
    names=[n for n in dir(AttemptTests) if n.startswith('test_attempt_') and '_zz_' not in n]
    names += [n for n in dir(AttemptTests) if n.startswith('test_portal_') and 'zz_' not in n]
    names += ['test_attempt_zz_owner_revocation_denies_all_worker_and_recovery_calls']
    class PrivateResult(unittest.TextTestResult):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw); self.error_types=[]; self.sqlstates=[]; self.constraints=[]
        def addError(self,t,e):
            self.error_types.append(e[0].__name__); self.sqlstates.append(getattr(e[1],'sqlstate',None) or 'none')
            name=getattr(getattr(e[1],'diag',None),'constraint_name',None)
            self.constraints.append(name if isinstance(name,str) and re.fullmatch(r'[a-z0-9_]{1,128}',name) else 'none'); super().addError(t,e)
    r=unittest.TextTestRunner(stream=io.StringIO(),resultclass=PrivateResult).run(unittest.TestSuite(AttemptTests(n) for n in names))
    print(json.dumps({'passed':r.wasSuccessful(),'tests_run':r.testsRun,'failed_tests':[getattr(t,'_testMethodName','setup') for t,_ in r.errors+r.failures],
                     'error_types':r.error_types,'sqlstates':r.sqlstates,'constraints':r.constraints}))
