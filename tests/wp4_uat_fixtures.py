"""Private fresh-DB fixtures. Two new pending cases, no owner decision/publication."""
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
import test_wp4_dispatch_database as foundation
from test_wp4_portal_publication_database import PortalPublicationTests


if __name__=='__main__':
    stage='initialization'
    try:
        foundation.CONFIG=json.loads(sys.stdin.read())
        PortalPublicationTests.setUpClass()
        admin=PortalPublicationTests.admin;owner=PortalPublicationTests.owner
        report=foundation.CONFIG['base']['report'];digest=sha256(report.encode()).hexdigest()
        cases={}
        stage='pending-cases'
        for name in ('browser','probe'):
            case=str(uuid4())
            admin.execute('INSERT INTO retail.report_cases(case_id,idempotency_key,request_identity) VALUES(%s,%s,%s::jsonb)',
                          (case,'uat-'+uuid4().hex,json.dumps(foundation.CONFIG['base']['request'])))
            admin.execute("INSERT INTO retail.report_audit_events(case_id,event_type) VALUES(%s,'request_received')",(case,))
            admin.execute("INSERT INTO retail.report_revisions(case_id,revision,schema_version,payload_text,payload_sha256) "
                          "VALUES(%s,1,'deterministic-comparison-report-v1',%s,%s)",(case,report,digest))
            admin.execute("UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1 WHERE case_id=%s",(case,))
            admin.execute("INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES(%s,'revision_created',1)",(case,))
            admin.commit()
            with psycopg.connect(**foundation.CONFIG['issuer']) as conn:
                conn.read_only=False
                value=json.loads(conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,NULL)',
                                              (case,digest,'uat-request-'+uuid4().hex)).fetchone()[0])
            cases[name]=dict(case_id=case,request_id=value['request']['proposal_id'],report_sha256=digest)
        raw=foundation.CONFIG['expired_session']
        stage='expired-session'
        from api.portal import session_csrf
        admin.execute("WITH moment AS (SELECT clock_timestamp() t) INSERT INTO retail.owner_portal_sessions "
                      "SELECT %s,%s,%s,t-interval '2 hours',t-interval '1 hour',NULL FROM moment",(sha256(raw.encode()).hexdigest(),owner,
                      sha256(session_csrf(raw).encode()).hexdigest()))
        admin.commit();PortalPublicationTests.tearDownClass()
        print(json.dumps(cases))
    except Exception as error:
        # Finite categories only; no SQL, exception text, payload or credentials.
        category='sql' if isinstance(error,psycopg.Error) else 'input' if isinstance(error,(ValueError,KeyError,TypeError)) else 'import' if isinstance(error,ImportError) else 'other'
        raise SystemExit('FAIL|private-uat-fixtures|'+stage+'|'+category+'|details-suppressed') from None
