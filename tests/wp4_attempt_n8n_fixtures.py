"""Private synthetic approvals, no raw source or real owner credentials in HTTP config."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_wp4_dispatch_database as foundation
from test_wp4_portal_attempts_database import AttemptTests


if __name__=='__main__':
    try:
        foundation.CONFIG=json.loads(sys.stdin.read())
        AttemptTests.setUpClass()
        t=AttemptTests('test_attempt_01_actual_scoped_roles_no_bypass_or_tables')
        plans={}
        for name in ('normal','state_retry503','lost_reserve','lost_accept','retry503','lost_report','lost_reconcile',
                     'cross_execution_budget','permanent401','stale_live','expired'):
            f=t.approved(seconds=1 if name=='expired' else None)
            plans[name]=dict(t.payload(f),action_id=f['action'],acceptance_key=f['key'])
        AttemptTests.tearDownClass()
        print(json.dumps(plans))
    except Exception:raise SystemExit('FAIL|private-attempt-n8n-fixture|details-suppressed') from None
