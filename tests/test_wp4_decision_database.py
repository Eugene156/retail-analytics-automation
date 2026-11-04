"""Private isolated database integration, not approval of a real report."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import io
import json
import re
import secrets
import sys
import threading
import time
import unittest
from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException
from api.main import Settings, create_app
from api.portal import PortalStore, digest, session_csrf, validate_receipt
from test_wp4_portal import call

CONFIG = None
PROBES = []
CASE = UUID('61b10574-c842-4dae-8e8b-647f0d51ba55')


class IsolatedStore(PortalStore):
    """Test-only connection guard. Production PortalStore remains fixed to validation DB."""
    def query(self, sql, arguments, write=False):
        with psycopg.connect(self.dsn,connect_timeout=5) as conn:
            conn.read_only=not write
            if conn.execute('SELECT current_user,current_database()').fetchone()!=('raa_wp4_portal_api',CONFIG['database']):
                raise RuntimeError('Wrong isolated connection')
            return conn.execute(sql,arguments).fetchone()[0]


@unittest.skipUnless(CONFIG is not None, 'Private isolated database input required')
class DecisionDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not re.fullmatch(r'raa_wp4_portal_test_[a-f0-9]{12}',CONFIG['database']):
            raise RuntimeError('Isolated test database required')
        cls.setup=psycopg.connect(**CONFIG['admin'])
        cls.owner=uuid4()
        cls.raw=secrets.token_hex(32)
        cls.csrf=session_csrf(cls.raw)
        PROBES.extend((cls.raw,cls.csrf,digest(cls.raw),digest(cls.csrf),digest(CONFIG['owner'])))
        cls.setup.execute("INSERT INTO retail.owner_credentials(reviewer_id,token_sha256) VALUES(%s,%s)",
                          (cls.owner,digest(CONFIG['owner'])))
        cls.setup.execute("INSERT INTO retail.approval_policies VALUES('local-publication-v1',%s,86400)",(cls.owner,))
        cls.setup.execute("INSERT INTO retail.report_cases(case_id,idempotency_key,request_identity) VALUES(%s,'isolated-base-020',%s::jsonb)",
                          (CASE,json.dumps(CONFIG['base']['request'])))
        cls.setup.execute("INSERT INTO retail.report_audit_events(case_id,event_type) VALUES(%s,'request_received')",(CASE,))
        cls.setup.execute("INSERT INTO retail.report_revisions(case_id,revision,schema_version,payload_text,payload_sha256) "
            "VALUES(%s,1,'deterministic-comparison-report-v1',%s,%s)",
            (CASE,CONFIG['base']['report'],sha256(CONFIG['base']['report'].encode()).hexdigest()))
        cls.setup.execute("UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1 WHERE case_id=%s",(CASE,))
        cls.setup.execute("INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES(%s,'revision_created',1)",(CASE,))
        cls.setup.execute(CONFIG['fixture_sql'])
        cls.setup.commit()
        with psycopg.connect(CONFIG['portal_dsn']) as conn:
            conn.read_only=False
            conn.execute('SELECT retail.api_portal_login_v1(%s,%s,%s,NULL)',
                         (digest(CONFIG['owner']),digest(cls.raw),digest(cls.csrf)))

    @classmethod
    def tearDownClass(cls):
        cls.setup.rollback()
        cls.setup.close()

    def fixture(self,expired=False):
        f=self.setup.execute('SELECT pg_temp.review_fixture_v1(%s)',(expired,)).fetchone()[0]
        self.setup.commit()
        PROBES.extend((f['session'],f['csrf']))
        return f

    def decision(self,conn,f,choice='approve',key='isolated-decision-020'):
        return conn.execute('SELECT retail.api_decide_request_v1(%s,%s,%s,%s,1,%s,%s,%s,%s)',
            (f['session'],f['csrf'],f['case'],f['proposal'],f['report_hash'],f['proposal_hash'],choice,key)).fetchone()[0]

    def test_actual_login_least_privilege(self):
        with psycopg.connect(CONFIG['portal_dsn']) as conn:
            self.assertEqual(conn.execute('SELECT current_user,current_database()').fetchone(),('raa_wp4_portal_api',CONFIG['database']))
            self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone(),('on',))
            self.assertTrue(conn.execute("SELECT has_function_privilege(current_user,"
                "'retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)','EXECUTE')").fetchone()[0])
            self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,'retail.review_decisions_v1','INSERT,SELECT')").fetchone()[0])
            self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,"
                "'retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid)','EXECUTE')").fetchone()[0])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('SELECT * FROM retail.publication_outbox_v1')
            conn.rollback()

    def test_two_simultaneous_and_ten_replays_one_bundle(self):
        f=self.fixture()
        barrier=threading.Barrier(2)
        def work():
            with psycopg.connect(CONFIG['portal_dsn']) as conn:
                conn.read_only=False
                barrier.wait(timeout=5)
                for attempt in range(3):
                    try:
                        result=self.decision(conn,f)
                        conn.commit()
                        return result
                    except psycopg.errors.LockNotAvailable:
                        conn.rollback()
                        if attempt==2: raise
                        time.sleep(.2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:work(),range(2)))
        self.assertEqual(results[0],results[1])
        with psycopg.connect(CONFIG['portal_dsn']) as conn:
            conn.read_only=False
            for _ in range(10):
                self.assertEqual(self.decision(conn,f),results[0]); conn.commit()
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                self.decision(conn,f,'reject'); conn.rollback()
        self.setup.rollback()
        counts=self.setup.execute('SELECT (SELECT count(*) FROM retail.review_decisions_v1 WHERE case_id=%s),'
            '(SELECT count(*) FROM retail.publication_outbox_v1 WHERE case_id=%s),'
            '(SELECT count(*) FROM retail.review_decision_events_v1 e JOIN retail.review_decisions_v1 d USING(decision_id) WHERE d.case_id=%s)',
            (f['case'],f['case'],f['case'])).fetchone()
        self.assertEqual(counts,(1,1,1))
        metadata=json.loads(self.setup.execute('SELECT retail.api_get_case_v1(%s)',(f['case'],)).fetchone()[0])
        self.assertEqual((metadata['state'],metadata['approved'],metadata['published']),('approved',True,False))
        self.assertEqual(metadata['review_receipt'],json.loads(results[0]))
        self.setup.rollback()
        self.setup.execute('SET LOCAL ROLE raa_wp4_reviewer_api')
        owner_case=json.loads(self.setup.execute('SELECT retail.api_owner_case_v1(%s,%s)',
            (digest(CONFIG['owner']),f['case'])).fetchone()[0])
        owner_request=json.loads(self.setup.execute('SELECT retail.api_owner_current_request_v2(%s,%s)',
            (digest(CONFIG['owner']),f['case'])).fetchone()[0])
        self.assertEqual(owner_case['state'],'approved')
        self.assertEqual((owner_request['review_status'],owner_request['approved'],owner_request['decision_enabled']),('approved',True,False))
        self.setup.rollback()

    def test_independent_case_owner_and_session_locks(self):
        f=self.fixture()
        lock_queries=[('SELECT 1 FROM retail.report_cases WHERE case_id=%s FOR UPDATE',(f['case'],)),
            ('SELECT 1 FROM retail.owner_credentials WHERE reviewer_id=%s FOR UPDATE',(self.owner,)),
            ('SELECT 1 FROM retail.owner_portal_sessions WHERE session_sha256=%s FOR UPDATE',(f['session'],))]
        for query,args in lock_queries:
            with psycopg.connect(**CONFIG['admin']) as holder,psycopg.connect(CONFIG['portal_dsn']) as contender:
                holder.execute(query,args)
                contender.read_only=False
                with self.assertRaises(psycopg.errors.LockNotAvailable): self.decision(contender,f)
                contender.rollback(); holder.rollback()
        self.setup.rollback()
        self.assertEqual(self.setup.execute('SELECT count(*) FROM retail.review_decisions_v1 WHERE case_id=%s',(f['case'],)).fetchone()[0],0)
        self.setup.rollback()

    def test_two_conflicting_choices_only_one_terminal_outcome(self):
        f=self.fixture(); barrier=threading.Barrier(2)
        def work(choice):
            with psycopg.connect(CONFIG['portal_dsn']) as conn:
                conn.read_only=False; barrier.wait(timeout=5)
                for attempt in range(3):
                    try:
                        result=self.decision(conn,f,choice,'isolated-conflict-'+choice)
                        conn.commit(); return json.loads(result)['decision']['outcome']
                    except psycopg.errors.LockNotAvailable:
                        conn.rollback()
                        if attempt==2: raise
                        time.sleep(.2)
                    except psycopg.errors.ObjectNotInPrerequisiteState:
                        conn.rollback(); return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(work,['approve','reject']))
        self.assertEqual(results.count('conflict'),1)
        winner=next(x for x in results if x!='conflict')
        self.setup.rollback()
        actual=self.setup.execute('SELECT (SELECT count(*) FROM retail.review_decisions_v1 WHERE case_id=%s),'
            '(SELECT count(*) FROM retail.publication_outbox_v1 WHERE case_id=%s)',(f['case'],f['case'])).fetchone()
        self.assertEqual(actual,(1,1 if winner=='approved' else 0))
        self.setup.rollback()

    def test_rollback_fault_and_projections_reject_expiry(self):
        for choice,expired in [('reject',False),('expire',True)]:
            f=self.fixture(expired)
            with psycopg.connect(CONFIG['portal_dsn']) as conn:
                conn.read_only=False
                result=json.loads(self.decision(conn,f,choice))
                self.assertIsNone(result['outbox'])
            self.setup.rollback()
            projection=json.loads(self.setup.execute('SELECT retail.api_get_approval_request_v2(%s,%s)',(f['case'],f['proposal'])).fetchone()[0])
            self.assertEqual(projection['review_status'],'rejected' if choice=='reject' else 'expired')
            metadata=json.loads(self.setup.execute('SELECT retail.api_get_case_v1(%s)',(f['case'],)).fetchone()[0])
            self.assertEqual(metadata['state'],'rejected' if choice=='reject' else 'awaiting_approval')
            self.setup.rollback()
        # Actual transaction rollback after writing a full bundle leaves no decision.
        f=self.fixture()
        with psycopg.connect(CONFIG['portal_dsn']) as conn:
            conn.read_only=False; self.decision(conn,f); conn.rollback()
        self.setup.rollback()
        self.assertEqual(self.setup.execute('SELECT count(*) FROM retail.review_decisions_v1 WHERE case_id=%s',(f['case'],)).fetchone()[0],0)
        self.setup.rollback()

    def test_asgi_confirmed_decision_real_db_redirect_receipt_preview(self):
        f=self.fixture()
        store=IsolatedStore(CONFIG['portal_dsn'],decisions_enabled=True)
        app=create_app(Settings('b'*64,'unused',portal_login_key='c'*64),portal_store=store)
        path='/portal/cases/'+f['case']+'/requests/'+f['proposal']
        headers=[(b'host',b'127.0.0.1:18081'),(b'cookie',('raa_portal_session='+self.raw).encode())]
        status,body,_=call(app,path,headers=headers)
        self.assertEqual(status,200); self.assertIn(b'Approve exact request',body)
        fields=dict((a.decode(),b.decode()) for a,b in re.findall(rb'<input type="hidden" name="([^"]+)" value="([^"]+)">',body))
        fields.update(choice='approve',confirm='yes')
        from urllib.parse import urlencode
        post_headers=headers+[(b'origin',b'http://127.0.0.1:18081'),(b'content-type',b'application/x-www-form-urlencoded')]
        bad={**fields,'csrf':'0'*64}
        self.assertEqual(call(app,path+'/decision','POST',urlencode(bad).encode(),post_headers)[0],403)
        self.assertEqual(call(app,path+'/decision','POST',urlencode(fields).encode(),post_headers)[0],303)
        self.assertEqual(call(app,path+'/decision','POST',urlencode(fields).encode(),post_headers)[0],303)
        status,body,_=call(app,path,headers=headers)
        self.assertEqual(status,200); self.assertIn(b'Status: approved',body)
        self.assertNotIn(b'Approve exact request',body); self.assertIn(b'Stored decision receipt',body)
        status,body,response_headers=call(app,'/portal/cases/'+f['case']+'/revisions/1/preview',headers=headers)
        self.assertEqual(status,200); self.assertIn(b'APPROVED',body); self.assertIn(b'UNPUBLISHED',body)
        self.assertEqual(dict(response_headers)[b'x-report-status'],b'approved-unpublished')
        self.assertNotIn(self.raw.encode(),body)
        self.setup.rollback()
        self.assertEqual(self.setup.execute('SELECT count(*) FROM retail.publication_outbox_v1 WHERE case_id=%s',(f['case'],)).fetchone()[0],1)
        self.setup.rollback()


if __name__=='__main__':
    CONFIG=json.loads(sys.stdin.read())
    # The decorator is evaluated before private input: activate only this guarded class.
    DecisionDatabaseTests.__unittest_skip__=False
    output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(DecisionDatabaseTests))
    print(json.dumps({'passed':result.wasSuccessful(),'tests_run':result.testsRun,
        'failed_tests':[test._testMethodName for test,_ in result.failures+result.errors], 'probe_values':PROBES}))
