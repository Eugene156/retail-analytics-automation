"""Private synthetic approval inputs for isolated crash/restore drills."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_wp4_dispatch_database as foundation
from test_wp4_portal_attempts_database import AttemptTests

if __name__=='__main__':
    try:
        foundation.CONFIG=json.loads(sys.stdin.read());AttemptTests.setUpClass()
        t=AttemptTests('test_attempt_01_actual_scoped_roles_no_bypass_or_tables')
        plans={}
        for name in ('api_before','api_after','n8n_reserve','pg_before','restore_live','restore_exhausted','restore_expired'):
            f=t.approved(seconds=1 if name=='restore_expired' else None)
            plans[name]=dict(t.payload(f),action_id=f['action'],acceptance_key=f['key'])
        AttemptTests.tearDownClass();print(json.dumps(plans))
    except Exception:raise SystemExit('FAIL|private-recovery-fixtures|details-suppressed') from None
