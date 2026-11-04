"""Private fresh-DB synthetic approvals for actual isolated n8n checks."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_wp4_dispatch_database as foundation
from test_wp4_portal_worker_database import WorkerTests

if __name__=='__main__':
    try:
        foundation.CONFIG=json.loads(sys.stdin.read())
        WorkerTests.setUpClass()
        t=WorkerTests('test_worker_01_actual_two_fixed_functions_no_auth_review_legacy_tables')
        plans={}
        for name in ('normal','state_retry503','retry503','lost_ack','exhaust503','permanent401','expired'):
            f=t.approved(seconds=1 if name=='expired' else None)
            plans[name]=dict(t.payload(f),action_id=f['action'],acceptance_key=f['key'])
        WorkerTests.tearDownClass()
        print(json.dumps(plans))
    except Exception:
        raise SystemExit('FAIL|private-n8n-fixture|details-suppressed') from None
