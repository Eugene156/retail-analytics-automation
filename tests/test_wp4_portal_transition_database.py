"""Private actual-login transition tests. No legacy file access or live renewal."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
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
from api.portal_publication import PortalOutcomeUncertain
from test_wp4_portal_review_v3_database import ReviewV3Tests
from test_wp4_portal_publication_reads_database import CommitFault
import test_wp4_dispatch_database as foundation


@unittest.skipUnless(foundation.CONFIG is not None, 'Private isolated database input required')
class TransitionTests(ReviewV3Tests):
    def legacy_fixture(self, seconds=-1):
        case, payload = self.bare_case()
        session, csrf = next(self.sessions)
        pid, key = str(uuid4()), 'legacy-'+uuid4().hex
        report_hash = payload['report_payload_sha256']
        size = len(foundation.CONFIG['base']['report'].encode())
        self.admin.execute("WITH moment AS (SELECT clock_timestamp() AS t) INSERT INTO retail.owner_portal_sessions "
            "SELECT %s,%s,%s,t-interval '1 minute',t+interval '59 minutes',NULL FROM moment", (session,self.owner,csrf))
        self.admin.execute("WITH moment AS (SELECT clock_timestamp()-interval '86400 seconds'+%s*interval '1 second' AS c), "
            "body AS (SELECT c,retail.approval_request_payload_v2(%s,%s,1,%s,%s,%s,c,c+interval '86400 seconds',1,%s,NULL,NULL) AS b FROM moment), "
            "saved AS (INSERT INTO retail.approval_requests_v2 SELECT %s,%s,1,1,%s,NULL,NULL,'local-publication-v1',%s,%s,%s,"
            "c,c+interval '86400 seconds',b,encode(sha256(convert_to(b,'UTF8')),'hex') FROM body RETURNING proposal_id,created_at) "
            "INSERT INTO retail.approval_request_events_v2(proposal_id,occurred_at) SELECT proposal_id,created_at FROM saved",
            (seconds,pid,case,report_hash,size,self.owner,key,pid,case,key,self.owner,report_hash,size))
        text, digest, expiry = self.admin.execute('SELECT payload_text,payload_sha256,expires_at FROM retail.approval_requests_v2 '
            'WHERE proposal_id=%s',(pid,)).fetchone()
        self.admin.commit()
        return dict(case=case, old=pid, old_hash=digest, old_text=text, report_hash=report_hash,
                    expires=expiry, session=session, csrf=csrf)

    def transition(self, f, key, conn=None):
        args=(f['case'],f['old'],f['old_hash'],f['report_hash'],key)
        if conn is not None:
            return json.loads(conn.execute('SELECT retail.api_transition_legacy_portal_v1(%s,%s,%s,%s,%s)',args).fetchone()[0])
        with self.connect('transition') as connection:
            return self.transition(f,key,connection)

    def legacy_issue(self, f, key, conn):
        return json.loads(conn.execute('SELECT retail.api_issue_approval_request_v2(%s,1,%s,%s,%s)',
            (f['case'],f['report_hash'],key,f['old'])).fetchone()[0])

    def legacy_decide(self, f, choice, conn):
        return json.loads(conn.execute('SELECT retail.api_decide_request_v1(%s,%s,%s,%s,1,%s,%s,%s,%s)',
            (f['session'],f['csrf'],f['case'],f['old'],f['report_hash'],f['old_hash'],choice,'legacy-decision-'+uuid4().hex)).fetchone()[0])

    def counts(self, case):
        row=self.admin.execute('SELECT (SELECT count(*) FROM retail.portal_legacy_transitions_v1 WHERE case_id=%s),'
            '(SELECT count(*) FROM retail.portal_approval_requests_v3 WHERE case_id=%s),'
            '(SELECT count(*) FROM retail.portal_legacy_transition_events_v1 e JOIN retail.portal_legacy_transitions_v1 t USING(transition_id) WHERE t.case_id=%s),'
            '(SELECT count(*) FROM retail.review_decisions_v1 WHERE case_id=%s),'
            '(SELECT count(*) FROM retail.publication_outbox_v1 WHERE case_id=%s)',(case,)*5).fetchone()
        self.admin.rollback()
        return row

    def assert_old_preserved(self,f):
        self.assertEqual(self.admin.execute('SELECT payload_text,payload_sha256 FROM retail.approval_requests_v2 WHERE proposal_id=%s',
            (f['old'],)).fetchone(),(f['old_text'],f['old_hash']))
        self.admin.rollback()

    def new_fixture(self,f,value):
        return dict(f,snapshot=value['new_request'])

    def short_transition(self,f,key,seconds=1.2):
        # Privileged synthetic backdating, never exposed by the transition API.
        tid,rid=str(uuid4()),str(uuid4())
        size=len(foundation.CONFIG['base']['report'].encode())
        created=self.admin.execute("SELECT clock_timestamp()-interval '86400 seconds'+%s*interval '1 second'",(seconds,)).fetchone()[0]
        body=self.admin.execute('SELECT retail.portal_request_payload_v3(%s,%s,%s,%s,%s,%s,%s,1,%s,NULL,NULL)',
            (rid,f['case'],f['report_hash'],size,self.owner,created,created+timedelta(seconds=86400),key)).fetchone()[0]
        digest=sha256(body.encode()).hexdigest()
        evidence=self.admin.execute('SELECT retail.portal_transition_payload_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (tid,f['case'],f['old'],f['old_hash'],rid,digest,f['report_hash'],self.owner,key,created)).fetchone()[0]
        self.admin.execute('INSERT INTO retail.portal_legacy_transitions_v1 VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (tid,f['case'],f['old'],f['old_hash'],rid,digest,f['report_hash'],self.owner,key,created,evidence,sha256(evidence.encode()).hexdigest()))
        self.admin.execute("INSERT INTO retail.portal_approval_requests_v3 VALUES(%s,%s,1,%s,'owner-portal-acceptance-v2',1,%s,NULL,NULL,%s,%s,%s,%s,%s,%s)",
            (rid,f['case'],self.owner,key,created,created+timedelta(seconds=86400),f['report_hash'],size,body,digest))
        self.admin.execute("INSERT INTO retail.portal_publication_audit_v2(subject_id,kind,occurred_at) VALUES(%s,'request_created',%s)",(rid,created))
        self.admin.execute("INSERT INTO retail.portal_legacy_transition_events_v1(transition_id,kind,occurred_at) VALUES(%s,'legacy_target_retired',%s)",(tid,created))
        value=json.loads(self.admin.execute('SELECT retail.portal_transition_snapshot_v1(%s)',(f['case'],)).fetchone()[0])
        self.admin.commit()
        return value

    def test_transition_scoped_login_one_function_and_private_helpers(self):
        with psycopg.connect(**foundation.CONFIG['transition']) as conn:
            self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0],'on')
            self.assertEqual(conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='retail' AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')").fetchone()[0],1)
            for table in ('portal_legacy_transitions_v1','approval_requests_v2','portal_approval_requests_v3'):
                self.assertFalse(conn.execute('SELECT has_table_privilege(current_user,%s,\'SELECT,INSERT,UPDATE,DELETE\')',('retail.'+table,)).fetchone()[0])
            self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,'retail.portal_transition_snapshot_v1(uuid)','EXECUTE')").fetchone()[0])
            self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,'retail.api_decide_portal_request_v2(text,text,uuid,text,text,text)','EXECUTE')").fetchone()[0])
        self.assertEqual(self.admin.execute("SELECT count(*) FROM pg_roles WHERE rolname='raa_wp4_portal_transition_v1' AND NOT rolcanlogin").fetchone()[0],1)
        self.assertEqual(self.admin.execute("SELECT count(*) FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='raa_wp4_portal_transition_v1')").fetchone()[0],0)
        self.admin.rollback()

    def test_transition_exact_bundle_ten_replays_new_deadline_no_approval(self):
        f,key=self.legacy_fixture(),'transition-'+uuid4().hex
        value=self.transition(f,key)
        for _ in range(10): self.assertEqual(self.transition(f,key),value)
        t,r=value['transition'],value['new_request']['request']
        self.assertEqual(sha256(value['canonical_transition_text'].encode()).hexdigest(),value['transition_sha256'])
        self.assertEqual(json.loads(value['canonical_transition_text']),t)
        self.assertEqual((t['legacy_request_id'],t['legacy_request_sha256'],t['first_request_id'],t['first_request_sha256']),
            (f['old'],f['old_hash'],r['proposal_id'],value['new_request']['request_sha256']))
        self.assertFalse(t['approval_transferred']); self.assertFalse(t['legacy_files_adopted'])
        self.assertEqual(r['generation'],1); self.assertIsNone(r['predecessor_proposal_id'])
        created,expiry=(datetime.fromisoformat(r[n]) for n in ('created_at','expires_at'))
        self.assertEqual(expiry-created,timedelta(seconds=86400))
        self.assertGreater(created,f['expires'])
        self.assertIsNone(value['new_request']['decision']); self.assertIsNone(value['new_request']['publication'])
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0)); self.assert_old_preserved(f)

    def test_transition_live_or_unknown_request_and_wrong_binding_denied(self):
        live=self.legacy_fixture(seconds=3600)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.transition(live,'live-'+uuid4().hex)
        f=self.legacy_fixture()
        for field,wrong in (('case',str(uuid4())),('old',str(uuid4())),('old_hash','0'*64),('report_hash','0'*64)):
            with self.assertRaises((psycopg.errors.ObjectNotInPrerequisiteState,psycopg.errors.NoDataFound)):
                self.transition(dict(f,**{field:wrong}),'bad-'+uuid4().hex)
        for badkey in ('short','bad key'):
            with self.assertRaises(psycopg.errors.InvalidParameterValue): self.transition(f,badkey)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))

    def test_transition_changed_replay_bindings_or_new_key_never_renew(self):
        f,key=self.legacy_fixture(),'replay-'+uuid4().hex
        value=self.transition(f,key)
        for field,wrong in (('old',str(uuid4())),('old_hash','0'*64),('report_hash','0'*64)):
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.transition(dict(f,**{field:wrong}),key)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.transition(f,'different-'+uuid4().hex)
        self.assertEqual(self.transition(f,key),value)
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))

    def test_transition_latest_legacy_predecessor_only(self):
        f=self.legacy_fixture()
        with self.connect('legacy') as conn: newer=self.legacy_issue(f,'successor-'+uuid4().hex,conn)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.transition(f,'stale-'+uuid4().hex)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))
        self.assertNotEqual(newer['proposal']['proposal_id'],f['old'])

    def test_transition_any_legacy_decision_blocks_even_recorded_expiry(self):
        for choice in ('approve','reject','expire'):
            f=self.legacy_fixture(seconds=1.2 if choice!='expire' else -1)
            with self.connect('legacy') as conn: self.legacy_decide(f,choice,conn)
            remaining=(f['expires']-datetime.now(f['expires'].tzinfo)).total_seconds()
            if remaining>0: time.sleep(remaining+0.08)
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.transition(f,'reviewed-'+uuid4().hex)
            self.assertEqual(self.counts(f['case']), (0,0,0,1,int(choice=='approve')))
            self.assert_old_preserved(f)

    def test_transition_uncertain_legacy_dispatch_not_adopted(self):
        f=self.legacy_fixture(seconds=1.2)
        with self.connect('legacy') as conn: old=self.legacy_decide(f,'approve',conn)
        action=old['outbox']
        with self.worker() as conn: self.claim(conn,action)
        remaining=(f['expires']-datetime.now(f['expires'].tzinfo)).total_seconds()
        if remaining>0: time.sleep(remaining+0.08)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.transition(f,'uncertain-'+uuid4().hex)
        self.assertEqual(self.counts(f['case']),(0,0,0,1,1))

    def test_transition_ordinary_new_issuance_cannot_bypass_legacy(self):
        f=self.legacy_fixture()
        with self.connect('issuer') as conn:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,NULL)',(f['case'],f['report_hash'],'bypass-'+uuid4().hex))
            conn.rollback()
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))

    def test_transition_fences_old_renewal_and_expiry_decision(self):
        f=self.legacy_fixture(); self.transition(f,'fence-'+uuid4().hex)
        with self.connect('legacy') as conn:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.legacy_issue(f,'late-old-'+uuid4().hex,conn)
            conn.rollback()
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.legacy_decide(f,'expire',conn)
            conn.rollback()
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0)); self.assert_old_preserved(f)

    def test_transition_concurrent_same_key_single_bundle(self):
        f,key=self.legacy_fixture(),'concurrent-'+uuid4().hex
        barrier=threading.Barrier(2)
        def run(_):
            barrier.wait(timeout=5)
            try: return self.transition(f,key)
            except psycopg.errors.LockNotAvailable: return None
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,range(2)))
        self.assertTrue(any(value is not None for value in results))
        winner=self.transition(f,key)
        self.assertTrue(all(value is None or value==winner for value in results))
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))

    def test_transition_held_legacy_issue_wins_then_stale_transition_denied(self):
        f=self.legacy_fixture()
        with self.connect('legacy') as old:
            self.legacy_issue(f,'held-legacy-'+uuid4().hex,old)
            with self.assertRaises(psycopg.errors.LockNotAvailable): self.transition(f,'race-'+uuid4().hex)
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.transition(f,'race-'+uuid4().hex)
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))

    def test_transition_held_transition_blocks_legacy_then_permanent_fence(self):
        f=self.legacy_fixture()
        with self.connect('transition') as new:
            self.transition(f,'held-new-'+uuid4().hex,new)
            with self.connect('legacy') as old:
                with self.assertRaises(psycopg.errors.LockNotAvailable): self.legacy_issue(f,'race-old-'+uuid4().hex,old)
                old.rollback()
        with self.connect('legacy') as old:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.legacy_issue(f,'race-old-'+uuid4().hex,old)
            old.rollback()
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))

    def test_transition_deferred_fault_rolls_back_retirement_and_request(self):
        f=self.legacy_fixture()
        self.admin.execute("CREATE FUNCTION pg_temp.transition_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Synthetic transition commit fault'; END $$")
        self.admin.execute('CREATE CONSTRAINT TRIGGER portal_transition_test_fault AFTER INSERT ON retail.portal_legacy_transitions_v1 '
            'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION pg_temp.transition_fault()')
        self.admin.commit()
        try:
            with self.assertRaises(psycopg.errors.RaiseException): self.transition(f,'fault-'+uuid4().hex)
            self.assertEqual(self.counts(f['case']),(0,0,0,0,0)); self.assert_old_preserved(f)
        finally:
            self.admin.execute('DROP TRIGGER portal_transition_test_fault ON retail.portal_legacy_transitions_v1'); self.admin.commit()
        with self.connect('legacy') as old: self.legacy_issue(f,'after-rollback-'+uuid4().hex,old)

    def test_transition_missing_request_or_event_cannot_commit(self):
        for tab in ('portal_approval_requests_v3','portal_legacy_transition_events_v1'):
            f=self.legacy_fixture()
            self.admin.execute("CREATE OR REPLACE FUNCTION pg_temp.omit_transition_row() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$")
            self.admin.execute('CREATE TRIGGER zz_transition_omit BEFORE INSERT ON retail.'+tab+' FOR EACH ROW EXECUTE FUNCTION pg_temp.omit_transition_row()')
            self.admin.commit()
            try:
                with self.assertRaises((psycopg.errors.RaiseException,psycopg.errors.ForeignKeyViolation)):
                    self.transition(f,'omit-'+uuid4().hex)
                self.assertEqual(self.counts(f['case']),(0,0,0,0,0))
            finally:
                self.admin.execute('DROP TRIGGER zz_transition_omit ON retail.'+tab); self.admin.commit()

    def test_transition_immutable_ledger_and_audit(self):
        f=self.legacy_fixture(); self.transition(f,'immutable-'+uuid4().hex)
        for tab in ('portal_legacy_transitions_v1','portal_legacy_transition_events_v1'):
            for sql in ('UPDATE retail.'+tab+" SET payload_text='{}'" if tab.endswith('transitions_v1') else 'UPDATE retail.'+tab+" SET kind='legacy_target_retired'",
                        'DELETE FROM retail.'+tab,'TRUNCATE retail.'+tab):
                with self.assertRaises((psycopg.errors.RaiseException,psycopg.errors.FeatureNotSupported)): self.admin.execute(sql)
                self.admin.rollback()
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))

    def test_transition_lost_ack_owner_read_and_same_key_reconcile_no_renewal(self):
        f,key=self.legacy_fixture(),'lost-ack-'+uuid4().hex
        store=self.store('transition')
        original=store.factory
        store.factory=lambda: CommitFault(original(),True)
        args=(f['case'],f['old'],f['old_hash'],f['report_hash'],key)
        with self.assertRaises(PortalOutcomeUncertain):
            store._query('SELECT retail.api_transition_legacy_portal_v1(%s,%s,%s,%s,%s)',args,write=True)
        with self.connect('reader') as reader:
            observed=json.loads(reader.execute('SELECT retail.api_owner_portal_transition_v1(%s,%s)',(f['session'],f['case'])).fetchone()[0])
        self.assertEqual(self.transition(f,key),observed)
        self.assertEqual(self.counts(f['case']),(1,1,1,0,0))

    def test_transition_fresh_owner_form_required_before_portal_publication(self):
        f=self.legacy_fixture(); value=self.transition(f,'fresh-approval-'+uuid4().hex)
        fresh=self.new_fixture(f,value)
        app,headers,_=self.browser(fresh)
        form=self.form(app,fresh,headers)
        self.assertNotEqual(form['proposal_sha256'],f['old_hash'])
        self.assertEqual(self.post(app,fresh,headers,dict(form,proposal_sha256=f['old_hash']))[0],409)
        self.assertEqual(self.bundle_count(value['transition']['first_request_id']),(0,0,0))
        self.assertEqual(self.post(app,fresh,headers,form)[0],303)
        approved=self.review_store().review(fresh['session'],fresh['case'],value['transition']['first_request_id'])
        self.assertEqual(self.bundle_count(value['transition']['first_request_id']),(1,1,0))
        self.store().accept(approved['action_id'],'new-target-'+uuid4().hex)
        self.assertEqual(self.bundle_count(value['transition']['first_request_id']),(1,1,1))
        self.assert_old_preserved(f)

    def test_transition_clean_new_target_case_also_fences_legacy_insert(self):
        fresh=self.fixture_portal()
        with self.connect('legacy') as conn:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                conn.execute('SELECT retail.api_issue_approval_request_v2(%s,1,%s,%s,NULL)',
                    (fresh['case'],fresh['snapshot']['request']['report_payload_sha256'],'clean-old-'+uuid4().hex))
            conn.rollback()

    def test_transition_expired_approved_new_request_needs_successor_fresh_approval(self):
        f,key=self.legacy_fixture(seconds=-86401),'short-transition-'+uuid4().hex
        value=self.short_transition(f,key)
        fresh=self.new_fixture(f,value)
        approved=self.decide_portal(fresh)
        self.wait_expired(value['transition']['first_request_id'])
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept_portal(approved)
        with self.connect('issuer') as conn:
            successor=json.loads(conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                (f['case'],f['report_hash'],'new-successor-'+uuid4().hex,value['transition']['first_request_id'])).fetchone()[0])
        self.assertEqual(successor['request']['generation'],2)
        self.assertIsNone(successor['decision']); self.assertIsNone(successor['publication'])
        replay=self.transition(f,key)
        self.assertEqual(replay['transition'],value['transition'])
        self.assertEqual(replay['new_request']['request'],value['new_request']['request'])
        self.assertFalse(replay['new_request']['is_current'])
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.accept_portal(approved)
        next_fixture=dict(f,snapshot=successor)
        next_approval=self.decide_portal(next_fixture)
        self.accept_portal(next_approval)
        self.assertEqual(self.counts(f['case']),(1,2,1,0,0)); self.assert_old_preserved(f)

    def test_transition_rejected_new_request_cannot_renew(self):
        live=self.legacy_fixture(seconds=-86401)
        live_value=self.short_transition(live,'reject-live-'+uuid4().hex)
        rejected=self.decide_portal(self.new_fixture(live,live_value),choice='reject')
        self.wait_expired(live_value['transition']['first_request_id'])
        with self.connect('issuer') as conn:
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                conn.execute('SELECT retail.api_issue_portal_request_v3(%s,%s,%s,%s)',
                    (live['case'],live['report_hash'],'rejected-successor-'+uuid4().hex,live_value['transition']['first_request_id']))
            conn.rollback()
        self.assertIsNone(rejected['action_id'])

    def test_transition_noncollision_ledger_tamper_cannot_commit(self):
        changes=("NEW.legacy_request_id:=gen_random_uuid();", "NEW.legacy_request_sha256:=repeat('0',64);",
                 "NEW.first_request_id:=gen_random_uuid();", "NEW.first_request_sha256:=repeat('0',64);",
                 "NEW.report_sha256:=repeat('0',64);", "NEW.reviewer_id:=gen_random_uuid();",
                 "NEW.request_key:='altered-transition-key';", "NEW.transitioned_at:=NEW.transitioned_at-interval '1 second';")
        for change in changes:
            f=self.legacy_fixture()
            self.admin.execute('CREATE OR REPLACE FUNCTION pg_temp.alter_transition_row() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN '+change+
                ' NEW.payload_text:=retail.portal_transition_payload_v1(NEW.transition_id,NEW.case_id,NEW.legacy_request_id,NEW.legacy_request_sha256,'
                'NEW.first_request_id,NEW.first_request_sha256,NEW.report_sha256,NEW.reviewer_id,NEW.request_key,NEW.transitioned_at); '
                "NEW.payload_sha256:=encode(sha256(convert_to(NEW.payload_text,'UTF8')),'hex'); RETURN NEW; END $$")
            self.admin.execute('CREATE TRIGGER a_transition_tamper BEFORE INSERT ON retail.portal_legacy_transitions_v1 FOR EACH ROW EXECUTE FUNCTION pg_temp.alter_transition_row()')
            self.admin.commit()
            try:
                with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState): self.transition(f,'tamper-'+uuid4().hex)
                self.assertEqual(self.counts(f['case']),(0,0,0,0,0)); self.assert_old_preserved(f)
            finally:
                self.admin.execute('DROP TRIGGER a_transition_tamper ON retail.portal_legacy_transitions_v1'); self.admin.commit()

    def test_transition_wrong_audit_time_cannot_commit(self):
        f=self.legacy_fixture()
        self.admin.execute("CREATE FUNCTION pg_temp.alter_transition_event() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.occurred_at:=NEW.occurred_at+interval '1 second'; RETURN NEW; END $$")
        self.admin.execute('CREATE TRIGGER a_transition_tamper BEFORE INSERT ON retail.portal_legacy_transition_events_v1 FOR EACH ROW EXECUTE FUNCTION pg_temp.alter_transition_event()')
        self.admin.commit()
        try:
            with self.assertRaises(psycopg.errors.RaiseException): self.transition(f,'audit-tamper-'+uuid4().hex)
            self.assertEqual(self.counts(f['case']),(0,0,0,0,0))
        finally:
            self.admin.execute('DROP TRIGGER a_transition_tamper ON retail.portal_legacy_transition_events_v1'); self.admin.commit()

    def test_transition_owner_reads_invalid_session_denied_and_no_mutation(self):
        f=self.legacy_fixture(); self.transition(f,'owner-read-'+uuid4().hex)
        before=self.counts(f['case'])
        with self.connect('reader') as conn:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('SELECT retail.api_owner_portal_transition_v1(%s,%s)',('0'*64,f['case']))
            conn.rollback()
            value=json.loads(conn.execute('SELECT retail.api_owner_portal_transition_v1(%s,%s)',(f['session'],f['case'])).fetchone()[0])
            self.assertEqual(value['transition']['legacy_request_sha256'],f['old_hash'])
        self.assertEqual(self.counts(f['case']),before)

    def test_transition_zz_revoked_owner_cannot_transition_or_read(self):
        f=self.legacy_fixture()
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s',(self.owner,)); self.admin.commit()
        with self.assertRaises(psycopg.errors.InsufficientPrivilege): self.transition(f,'revoked-'+uuid4().hex)
        with self.connect('reader') as conn:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('SELECT retail.api_owner_portal_transition_v1(%s,%s)',(f['session'],f['case']))
            conn.rollback()
        self.assertEqual(self.counts(f['case']),(0,0,0,0,0))


if __name__=='__main__':
    foundation.CONFIG=json.loads(sys.stdin.read())
    TransitionTests.__unittest_skip__=False
    # Rerun 17 original foundation tests against the changed 025 guard too.
    # Its old owner-revocation test is replaced by our final revocation test.
    suite=unittest.TestSuite(TransitionTests(name) for name in dir(TransitionTests)
        if name.startswith('test_transition_') or (name.startswith('test_portal_') and '_zz_' not in name))
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
