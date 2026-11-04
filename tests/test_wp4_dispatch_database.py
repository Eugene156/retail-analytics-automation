"""Isolated real-DB contract tests. Observations are simulated; no file writer."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import io
import json
import re
import sys
import threading
import time
import unittest
from uuid import uuid4
import psycopg

CONFIG=None
BASE='61b10574-c842-4dae-8e8b-647f0d51ba55'


@unittest.skipUnless(CONFIG is not None,'Private isolated database input required')
class DispatchDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not re.fullmatch(r'raa_wp4_dispatch_test_[a-f0-9]{12}',CONFIG['database']):
            raise RuntimeError('Isolated test DB required')
        cls.admin=psycopg.connect(**CONFIG['admin'])
        cls.owner=uuid4()
        cls.admin.execute('INSERT INTO retail.owner_credentials(reviewer_id,token_sha256) VALUES(%s,%s)',(cls.owner,CONFIG['owner_hash']))
        cls.admin.execute("INSERT INTO retail.approval_policies VALUES('local-publication-v1',%s,86400)",(cls.owner,))
        cls.admin.execute("INSERT INTO retail.report_cases(case_id,idempotency_key,request_identity) VALUES(%s,'dispatch-base-021',%s::jsonb)",
            (BASE,json.dumps(CONFIG['base']['request'])))
        cls.admin.execute("INSERT INTO retail.report_audit_events(case_id,event_type) VALUES(%s,'request_received')",(BASE,))
        report=CONFIG['base']['report']
        cls.admin.execute("INSERT INTO retail.report_revisions(case_id,revision,schema_version,payload_text,payload_sha256) "
            "VALUES(%s,1,'deterministic-comparison-report-v1',%s,%s)",(BASE,report,sha256(report.encode()).hexdigest()))
        cls.admin.execute("UPDATE retail.report_cases SET state='awaiting_approval',current_revision=1 WHERE case_id=%s",(BASE,))
        cls.admin.execute("INSERT INTO retail.report_audit_events(case_id,event_type,revision) VALUES(%s,'revision_created',1)",(BASE,))
        cls.admin.execute(CONFIG['fixture_sql'])
        short=CONFIG['fixture_sql'].split('CREATE FUNCTION pg_temp.decide_fixture_v1')[0]
        short=short.replace('review_fixture_v1','short_review_fixture_v1').replace('ELSE clock_timestamp() END',
            "ELSE clock_timestamp()-interval '23 hours 59 minutes 58 seconds' END")
        cls.admin.execute(short)
        cls.admin.commit()

    @classmethod
    def tearDownClass(cls):
        cls.admin.rollback(); cls.admin.close()

    def worker(self):
        conn=psycopg.connect(**CONFIG['worker']); conn.read_only=False
        self.assertEqual(conn.execute('SELECT current_database()').fetchone()[0],CONFIG['database'])
        return conn

    def fixture(self,short=False,choice='approve'):
        name='short_review_fixture_v1' if short else 'review_fixture_v1'
        f=self.admin.execute('SELECT pg_temp.'+name+'(%s)',(choice=='expire',)).fetchone()[0]
        value=self.admin.execute('SELECT pg_temp.decide_fixture_v1(%s::jsonb,%s,%s)',
            (json.dumps(f),choice,'dispatch-decision-'+uuid4().hex)).fetchone()[0]
        self.admin.commit()
        return json.loads(value)['outbox']

    def claim(self,conn,a,mode='reconcile',key=None):
        return json.loads(conn.execute('SELECT retail.api_claim_publication_v1(%s,%s,%s)',
            (a['action_id'],mode,key or 'dispatch-claim-'+uuid4().hex)).fetchone()[0])

    def observe(self,conn,a,lease,result='missing',hash_value=None,byte_count=None):
        if result=='matching' and hash_value is None:
            hash_value=a['content_sha256']; byte_count=a['content_bytes']
        return json.loads(conn.execute('SELECT retail.api_observe_publication_v1(%s,%s,%s,%s,%s)',
            (a['action_id'],lease,result,hash_value,byte_count)).fetchone()[0])

    def authorize(self,conn,a,lease):
        return conn.execute('SELECT retail.api_authorize_publication_v1(%s,%s)',(a['action_id'],lease)).fetchone()[0]

    def ready(self,conn,a,key=None):
        recon=self.claim(conn,a)
        self.assertFalse(recon['write_allowed'])
        self.assertEqual(self.observe(conn,a,recon['lease_id'])['state'],'retryable')
        return self.claim(conn,a,'write',key)

    def test_actual_login_four_functions_no_table_or_decision_rights(self):
        with psycopg.connect(**CONFIG['worker']) as conn:
            self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0],'on')
            self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,'retail.publication_dispatch_events_v1','SELECT,INSERT,UPDATE')").fetchone()[0])
            self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,'retail.api_decide_request_v1(text,text,uuid,uuid,integer,text,text,text,text)','EXECUTE')").fetchone()[0])
            self.assertEqual(conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='retail' AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')").fetchone()[0],4)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): conn.execute('SELECT * FROM retail.publication_outbox_v1')
            conn.rollback()
            self.assertFalse(conn.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='raa_wp4_dispatch_api'").fetchone()[0])

    def test_missing_first_then_write_success_and_ten_receipt_replays(self):
        a=self.fixture()
        with self.worker() as conn:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.claim(conn,a,'write')
            conn.rollback()
            write=self.ready(conn,a)
            self.assertEqual(write['write_attempts'],1); self.assertTrue(write['write_allowed'])
            self.assertEqual(write['content_text'].encode(),CONFIG['base']['report'].encode())
            self.assertTrue(self.authorize(conn,a,write['lease_id']))
            done=self.observe(conn,a,write['lease_id'],'matching')
            self.assertEqual(done['state'],'succeeded'); self.assertEqual(done['sequence'],4)
            for _ in range(10):
                again=self.observe(conn,a,write['lease_id'],'matching')
                self.assertEqual(again['sequence'],4); self.assertFalse(again['write_allowed'])
            self.assertFalse(self.authorize(conn,a,write['lease_id']))
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.claim(conn,a)
            conn.rollback()

    def test_matching_existing_file_observation_needs_no_write_attempt(self):
        a=self.fixture()
        with self.worker() as conn:
            read=self.claim(conn,a)
            done=self.observe(conn,a,read['lease_id'],'matching')
            self.assertEqual((done['state'],done['write_attempts']),('succeeded',0))

    def test_unknown_reconciles_before_retry_and_three_attempt_cap(self):
        a=self.fixture()
        with self.worker() as conn:
            write=self.ready(conn,a)
            for attempt in range(1,4):
                self.assertEqual(write['write_attempts'],attempt)
                unknown=self.observe(conn,a,write['lease_id'],'unknown')
                self.assertEqual(unknown['state'],'unknown')
                with conn.transaction():
                    with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                        with conn.transaction(): self.claim(conn,a,'write')
                read=self.claim(conn,a)
                missing=self.observe(conn,a,read['lease_id'])
                if attempt==3:
                    self.assertEqual(missing['state'],'dead_letter')
                else: write=self.claim(conn,a,'write')
            self.assertFalse(self.authorize(conn,a,write['lease_id']))

    def test_bad_observations_and_stale_tokens_leave_history_unchanged(self):
        a=self.fixture()
        with self.worker() as conn:
            read=self.claim(conn,a)
            for args in ((uuid4(),'matching',a['content_sha256'],a['content_bytes']),
                         (read['lease_id'],'matching','0'*64,a['content_bytes']),
                         (read['lease_id'],'missing',a['content_sha256'],a['content_bytes'])):
                with self.assertRaises(psycopg.Error):
                    with conn.transaction(): self.observe(conn,a,*args)
            done=self.observe(conn,a,read['lease_id'],'ambiguous')
            self.assertEqual(done['state'],'dead_letter'); self.assertEqual(done['sequence'],2)

    def test_two_concurrent_same_key_claims_and_ten_replays_one_lease(self):
        a=self.fixture(); key='concurrent-claim-'+uuid4().hex; barrier=threading.Barrier(2)
        def work():
            with self.worker() as conn:
                barrier.wait(timeout=5)
                for attempt in range(3):
                    try: return self.claim(conn,a,key=key)
                    except psycopg.errors.LockNotAvailable:
                        conn.rollback(); time.sleep(.05*(attempt+1))
                        if attempt==2: raise
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda _:work(),range(2)))
        self.assertEqual(values[0]['lease_id'],values[1]['lease_id'])
        with self.worker() as conn:
            for _ in range(10):
                self.assertEqual(self.claim(conn,a,key=key)['lease_expires_at'],values[0]['lease_expires_at'])
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with conn.transaction(): self.claim(conn,a)
            self.assertEqual(self.observe(conn,a,values[0]['lease_id'])['sequence'],2)

    def test_expired_lease_is_not_reused_or_blindly_retried(self):
        a=self.fixture(); key='crashed-claim-'+uuid4().hex
        with self.worker() as conn:
            read=self.ready(conn,a,key=key)
        # Real committed lease and connection close, not an UPDATE of history.
        time.sleep(30.1)
        with self.worker() as conn:
            replay=self.claim(conn,a,'write',key=key)
            self.assertEqual(replay['lease_id'],read['lease_id'])
            self.assertEqual(replay['lease_expires_at'],read['lease_expires_at'])
            self.assertFalse(replay['lease_active'])
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with conn.transaction(): self.claim(conn,a,'write')
            current=self.claim(conn,a)
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with conn.transaction(): self.observe(conn,a,read['lease_id'],'matching')
            self.assertEqual(self.observe(conn,a,current['lease_id'],'matching')['state'],'succeeded')

    def test_historical_claim_and_observation_replay_never_grant_current_lease(self):
        a=self.fixture(); key='historical-claim-'+uuid4().hex
        with self.worker() as conn:
            read=self.claim(conn,a,key=key)
            self.observe(conn,a,read['lease_id'])
            write=self.claim(conn,a,'write')
            old=self.claim(conn,a,key=key)
            self.assertEqual(old['lease_id'],read['lease_id'])
            self.assertFalse(old['lease_active']); self.assertFalse(old['write_allowed'])
            self.assertNotIn('content_text',old)
            self.assertFalse(self.authorize(conn,a,old['lease_id']))
            old_observation=self.observe(conn,a,read['lease_id'])
            self.assertFalse(old_observation['lease_active']); self.assertFalse(old_observation['write_allowed'])
            self.assertEqual(old_observation['lease_id'],read['lease_id'])
            self.assertTrue(self.authorize(conn,a,write['lease_id']))
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with conn.transaction(): self.claim(conn,a,'write',key=key)
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                with conn.transaction(): self.observe(conn,a,read['lease_id'],'matching')

    def test_matching_reconciliation_after_expiry_records_history_not_authorization(self):
        a=self.fixture(short=True)
        with self.worker() as conn: write=self.ready(conn,a)
        time.sleep(2.2)
        with self.worker() as conn:
            self.assertFalse(self.authorize(conn,a,write['lease_id']))
            self.observe(conn,a,write['lease_id'],'unknown')
            read=self.claim(conn,a)
            self.assertFalse(read['write_allowed'])
            done=self.observe(conn,a,read['lease_id'],'matching')
            self.assertEqual(done['state'],'succeeded'); self.assertEqual(done['write_attempts'],1)
            self.assertFalse(self.authorize(conn,a,write['lease_id']))

    def test_expiry_cancels_missing_target_without_renewal(self):
        a=self.fixture(short=True)
        with self.worker() as conn:
            write=self.ready(conn,a)
        time.sleep(2.2)
        with self.worker() as conn:
            self.assertFalse(self.authorize(conn,a,write['lease_id']))
            self.assertEqual(self.observe(conn,a,write['lease_id'],'missing')['state'],'unknown')
            read=self.claim(conn,a)
            self.assertEqual(self.observe(conn,a,read['lease_id'])['state'],'cancelled')

    def test_immutable_events_and_actual_insert_fault_rollback(self):
        a=self.fixture()
        with self.worker() as conn: self.claim(conn,a)
        for statement in ('UPDATE retail.publication_dispatch_events_v1 SET state=state',
                          'DELETE FROM retail.publication_dispatch_events_v1','TRUNCATE retail.publication_dispatch_events_v1'):
            with self.assertRaises(psycopg.Error):
                with self.admin.transaction(): self.admin.execute(statement)
        self.admin.rollback()
        b=self.fixture()
        with self.assertRaises(psycopg.Error):
            with self.admin.transaction():
                self.admin.execute("CREATE FUNCTION pg_temp.dispatch_fault() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    "BEGIN RAISE EXCEPTION 'Synthetic dispatch audit fault'; END $$; "
                    "CREATE TRIGGER dispatch_test_fault AFTER INSERT ON retail.publication_dispatch_events_v1 "
                    "FOR EACH ROW EXECUTE FUNCTION pg_temp.dispatch_fault();")
                self.claim(self.admin,b)
        self.admin.rollback()
        self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.publication_dispatch_events_v1 WHERE action_id=%s',(b['action_id'],)).fetchone()[0],0)
        self.admin.rollback()

    def test_owner_lock_blocks_revocation_during_authorization_transaction(self):
        a=self.fixture()
        with self.worker() as conn:
            write=self.ready(conn,a); self.assertTrue(self.authorize(conn,a,write['lease_id']))
            with psycopg.connect(**CONFIG['admin']) as other:
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    other.execute('SELECT 1 FROM retail.owner_credentials WHERE reviewer_id=%s FOR UPDATE NOWAIT',(self.owner,))
                other.rollback()

    def test_reject_and_expire_never_create_intents(self):
        self.assertIsNone(self.fixture(choice='reject'))
        self.assertIsNone(self.fixture(choice='expire'))

    def test_zz_revoked_owner_cancels_known_missing_and_denies_new_write(self):
        a=self.fixture()
        with self.worker() as conn:
            read=self.claim(conn,a); self.observe(conn,a,read['lease_id'])
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s',(self.owner,))
        self.admin.commit()
        with self.worker() as conn:
            cancelled=self.claim(conn,a,'write')
            self.assertEqual(cancelled['state'],'cancelled'); self.assertEqual(cancelled['write_attempts'],0)
            self.assertFalse(self.authorize(conn,a,uuid4()))


if __name__=='__main__':
    CONFIG=json.loads(sys.stdin.read())
    DispatchDatabaseTests.__unittest_skip__=False
    class PrivateResult(unittest.TextTestResult):
        error_types=[]
        def addError(self,test,error):
            self.error_types.append(error[0].__name__); super().addError(test,error)
    result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=PrivateResult).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(DispatchDatabaseTests))
    print(json.dumps({'passed':result.wasSuccessful(),'tests_run':result.testsRun,
        'failed_tests':[getattr(t,'_testMethodName','class_setup') for t,_ in result.errors+result.failures],
        'error_types':result.error_types}))
