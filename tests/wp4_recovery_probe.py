"""Fixed private worker/operator drill probes, no admin/owner in service config."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from fastapi import HTTPException
from api.portal_attempts import IsolatedAttemptWorker,IsolatedAttemptRecovery
from api.portal_publication import IsolatedPortalPublicationStore


def adapter(p,kind='attempt_worker'):
    db=p[kind]
    cls=IsolatedAttemptRecovery if kind=='recovery' else IsolatedAttemptWorker
    return cls(IsolatedPortalPublicationStore(lambda:psycopg.connect(**db),p['database'],db['user']))


def run(p):
    worker=adapter(p);f=p['plan'];action,key=f['action_id'],f['acceptance_key']
    mode=p['mode']
    if mode=='scope':
        with psycopg.connect(**p['attempt_worker']) as conn:
            if conn.execute('SHOW transaction_read_only').fetchone()[0]!='on':raise ValueError()
            n=conn.execute("SELECT count(*) FROM pg_proc f JOIN pg_namespace n ON n.oid=f.pronamespace WHERE n.nspname='retail' AND f.prosecdef AND has_function_privilege(current_user,f.oid,'EXECUTE')").fetchone()[0]
            if n!=5:raise ValueError()
            for tab in ('portal_worker_events_v1','portal_publications_v2','owner_credentials'):
                if conn.execute("SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE,DELETE')",('retail.'+tab,)).fetchone()[0]:raise ValueError()
            if conn.execute("SELECT has_function_privilege(current_user,'retail.api_operator_reconcile_portal_v1(uuid,text,text)','EXECUTE')").fetchone()[0]:raise ValueError()
        return {'restricted':True,'functions':5}
    if mode in ('seed_live','seed_exhausted'):
        for ordinal in range(1,4 if mode=='seed_exhausted' else 2):
            r=worker.reserve(action,key,{**{n:f[n] for n in ('case_id','request_sha256','report_sha256')},
                'attempt_key':'restore-seed-slot-'+str(ordinal),'execution_id':str(88888000+ordinal)})
            if not r['reservation_acknowledged']:raise ValueError()
            if mode=='seed_exhausted':worker.report(action,key,{'attempt_id':r['ledger']['attempt_id'],'execution_id':r['ledger']['execution_id'],'outcome':'retryable'})
        return worker.state(action,key)
    if mode=='fence_restored':
        # Explicit operator drill, BEFORE a restored HTTP worker is started.
        old=worker.state(action,key)['ledger'];deadline=time.monotonic()+35
        while worker.state(action,key)['ledger']['state']=='reserved':
            if time.monotonic()>deadline:raise ValueError()
            time.sleep(.25)
        recovery=adapter(p,'recovery')
        result=recovery.recover(action,key,{'recovery_key':'isolated-restore-fence-v1'})
        if result['ledger']['state']!='retryable' or result['ledger']['attempt_count']!=old['attempt_count']:raise ValueError()
        try:worker.accept(action,key,{'attempt_id':old['attempt_id'],'execution_id':old['execution_id']})
        except HTTPException as error:
            # A logical restore may copy an xid beyond the new cluster's xid
            # horizon. PostgreSQL's invalid-xid denial maps to the existing422;
            # do not weaken the API or treat any failed GET as fencing proof.
            if error.status_code not in (409,422,503):raise ValueError()
            status=error.status_code
        else:raise ValueError()
        checked=worker.state(action,key)
        if checked['ledger']!=result['ledger'] | {'observed_at':checked['ledger']['observed_at']} or checked['worker']['receipt'] is not None:raise ValueError()
        return {'state':'retryable','attempt_count':result['ledger']['attempt_count'],'stale_accept_denied':True,'stale_accept_status':status}
    if mode=='state':return worker.state(action,key)
    raise ValueError()


if __name__=='__main__':
    try:print(json.dumps(run(json.loads(sys.stdin.read()))))
    except Exception:raise SystemExit('FAIL|fixed-recovery-probe|details-suppressed') from None
