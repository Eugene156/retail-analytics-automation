"""Private actual SQL / ASGI auth checks; no listener or native browser claim."""
from datetime import datetime, timedelta
from hashlib import sha256
import hmac
import io
import json
import re
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

import psycopg
from fastapi import FastAPI

from api.portal import CHALLENGE, SESSION, digest, session_csrf
from api.portal_auth_v2 import IsolatedPortalAuth, install_isolated_auth_v2
from test_wp4_portal import call
from test_wp4_portal_transition_api_database import TransitionAPITests
from test_wp4_portal_publication_reads_database import CommitFault
import test_wp4_dispatch_database as foundation


class AuthCommitFault(CommitFault):
    """Only inject at auth writes, not the guard's preceding identity read."""
    def __init__(self, connection, after):
        super().__init__(connection, after)
        object.__setattr__(self, 'auth_write', False)

    def execute(self, query, *args, **kwargs):
        if 'api_portal_auth_login_v2(' in query or 'api_portal_auth_logout_v2(' in query:
            object.__setattr__(self, 'auth_write', True)
        return self.connection.execute(query, *args, **kwargs)

    def commit(self):
        if self.auth_write:
            return super().commit()
        return self.connection.commit()


class AuthResultFault(AuthCommitFault):
    def execute(self, query, *args, **kwargs):
        result = self.connection.execute(query, *args, **kwargs)
        if 'api_portal_auth_login_v2(' in query:
            value = json.loads(result.fetchone()[0])
            value['expires_at'] = value['created_at']
            return type('InvalidResult', (), {'fetchone': lambda _: (json.dumps(value),)})()
        if 'api_portal_auth_logout_v2(' in query:
            return type('InvalidResult', (), {'fetchone': lambda _: (False,)})()
        return result


@unittest.skipUnless(foundation.CONFIG is not None, 'Private isolated database input required')
class AuthTests(TransitionAPITests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.random_pool = iter(foundation.CONFIG['auth_random'])

    def setUp(self):
        # Cryptographic values were generated/registered privately on the host.
        self.entropy = patch('api.portal.secrets.token_hex', side_effect=lambda n: next(self.random_pool)[:2*n])
        self.clock = patch('api.portal.time.time', return_value=foundation.CONFIG['auth_clock'])
        self.entropy.start(); self.clock.start()
        self.addCleanup(self.entropy.stop); self.addCleanup(self.clock.stop)

    def tearDown(self):
        self.admin.rollback()
        # Explicit isolated admin cleanup; history retained, not product logout.
        self.admin.execute('UPDATE retail.owner_portal_sessions SET revoked_at=GREATEST(clock_timestamp(),created_at) '
                           'WHERE reviewer_id=%s AND revoked_at IS NULL', (self.owner,))
        self.admin.commit()

    def review_store(self, factory=None):
        return IsolatedPortalAuth(self.store('reader'), self.store('reviewer'), self.store('issuer'),
                                  self.store('transition'), self.store('auth', factory))

    def app(self, review=None):
        app = FastAPI()
        install_isolated_auth_v2(app, review or self.review_store(), foundation.CONFIG['portal_key'], foundation.CONFIG['service_token'])
        return app

    @staticmethod
    def cookie(headers, name):
        for key, value in headers:
            if key == b'set-cookie' and value.startswith((name+'=').encode()):
                return value.decode().split(';')[0].split('=', 1)[1].strip('"')
        return None

    @staticmethod
    def owner_headers(raw):
        return [(b'host', b'127.0.0.1:18081'), (b'cookie', (SESSION+'='+raw).encode())]

    def challenge(self, app):
        status, body, headers = call(app, '/portal/login', headers=[(b'host', b'127.0.0.1:18081')])
        self.assertEqual(status, 200)
        nonce = re.search(rb'name="csrf" value="([a-f0-9]{64})"', body).group(1).decode()
        signed = self.cookie(headers, CHALLENGE)
        self.assertTrue(signed.startswith(nonce+'.'))
        return nonce, signed

    def sign_in(self, app, owner=None, old=None, challenge=None, extra=None):
        nonce, signed = challenge or self.challenge(app)
        cookie = CHALLENGE+'='+signed + ('; '+SESSION+'='+old if old else '')
        headers = [(b'host', b'127.0.0.1:18081'), (b'cookie', cookie.encode()),
                   (b'origin', b'http://127.0.0.1:18081'), (b'content-type', b'application/x-www-form-urlencoded')]
        if extra:
            headers += extra
        return call(app, '/portal/login', 'POST', urlencode({'owner_token': owner if owner is not None else
                    foundation.CONFIG['owner_token'], 'csrf': nonce}).encode(), headers=headers)

    def signed_in(self, app=None):
        app = app or self.app()
        status, _, headers = self.sign_in(app)
        self.assertEqual(status, 303)
        raw = self.cookie(headers, SESSION)
        self.assertIsNotNone(raw)
        return app, self.owner_headers(raw), raw

    def sign_out(self, app, raw, csrf=None):
        return call(app, '/portal/logout', 'POST', urlencode({'csrf': csrf or session_csrf(raw)}).encode(),
                    headers=self.owner_headers(raw)+[(b'origin', b'http://127.0.0.1:18081'),
                            (b'content-type', b'application/x-www-form-urlencoded')])

    def auth_counts(self):
        row = self.admin.execute('SELECT (SELECT count(*) FROM retail.owner_portal_sessions),'
                                '(SELECT count(*) FROM retail.owner_portal_events)').fetchone()
        self.admin.rollback()
        return row

    def session_row(self, raw):
        row = self.admin.execute('SELECT created_at,expires_at,revoked_at FROM retail.owner_portal_sessions '
                                'WHERE session_sha256=%s', (digest(raw),)).fetchone()
        self.admin.rollback()
        return row

    def test_auth_01_actual_three_function_auth_no_business_or_old_auth_grants(self):
        for kind, expected in (('auth',3), ('reader',8), ('reviewer',2), ('issuer',1), ('transition',2)):
            with psycopg.connect(**foundation.CONFIG[kind]) as conn:
                self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone()[0], 'on')
                self.assertEqual(conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='retail' AND p.prosecdef AND has_function_privilege(current_user,p.oid,'EXECUTE')").fetchone()[0], expected)
                for tab in ('owner_portal_sessions','owner_portal_events','owner_credentials','portal_approval_requests_v3'):
                    self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE,DELETE')", ('retail.'+tab,)).fetchone()[0])
                for fn in ('api_portal_login_v1(text,text,text,text)','api_portal_logout_v1(text,text)'):
                    self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')", ('retail.'+fn,)).fetchone()[0])
                self.assertEqual(conn.execute("SELECT has_function_privilege(current_user,'retail.api_portal_auth_login_v2(text,text,text,text)','EXECUTE')").fetchone()[0], kind=='auth')
        self.assertEqual(self.admin.execute("SELECT count(*) FROM pg_roles WHERE rolname='raa_wp4_portal_auth_v2' "
                                           'AND NOT rolcanlogin AND NOT rolsuper').fetchone()[0],1)
        self.assertEqual(self.admin.execute("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid "
                                           "WHERE r.rolname='raa_wp4_portal_auth_v2'").fetchone()[0],0)
        self.admin.rollback()

    def test_auth_02_anonymous_challenge_headers_single_routes_and_guard(self):
        app = self.app()
        self.assertEqual(call(app, '/portal', headers=[(b'host',b'127.0.0.1:18081')])[0],303)
        status, body, headers = call(app, '/portal/login', headers=[(b'host',b'127.0.0.1:18081')])
        self.assertEqual(status,200)
        self.assertIn(b'one hour',body); self.assertIn(b'24 hours',body)
        self.assertIn(b'Isolated validation',body); self.assertNotIn(foundation.CONFIG['owner_token'].encode(),body)
        challenge_header = next(v for k,v in headers if k==b'set-cookie')
        for flag in (b'HttpOnly',b'Max-Age=300',b'Path=/portal/login',b'SameSite=strict'):
            self.assertIn(flag,challenge_header)
        self.assertEqual(dict(headers)[b'cache-control'],b'no-store')
        self.assertEqual(dict(headers)[b'referrer-policy'],b'same-origin')
        for path, method in (('/portal','GET'),('/portal/login','GET'),('/portal/login','POST'),('/portal/logout','POST')):
            self.assertEqual(sum(r.path==path and method in (getattr(r,'methods',None) or ()) for r in app.routes),1)
        self.assertEqual(sum(m.cls.__name__=='PortalGuard' for m in app.user_middleware),1)

    def test_auth_03_login_absolute_hour_and_reads_never_renew_or_approve(self):
        f = self.fixture_portal(); original = f['snapshot']['canonical_payload_text']
        app, headers, raw = self.signed_in()
        row = self.session_row(raw)
        self.assertEqual(row[1]-row[0],timedelta(seconds=3600)); self.assertIsNone(row[2])
        for _ in range(10):
            for path in ('/portal', self.detail(f)):
                status, body, _ = call(app,path,headers=headers)
                self.assertEqual(status,200); self.assertIn(b'Sign out',body)
                self.assertNotIn(raw.encode(),body)
        self.assertEqual(self.session_row(raw),row)
        self.assertEqual(self.review_store().review(digest(raw), f['case'], f['snapshot']['request']['proposal_id'])['canonical_payload_text'],original)
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']),(0,0,0))
        self.assertEqual(self.admin.execute("SELECT count(*) FROM retail.owner_portal_events WHERE session_sha256=%s AND event_type='login'", (digest(raw),)).fetchone()[0],1)
        self.admin.rollback()

    def test_auth_04_rotation_revokes_old_session_preserves_request_and_history(self):
        f = self.fixture_portal(); app, headers, old = self.signed_in()
        status, _, result = self.sign_in(app,old=old)
        self.assertEqual(status,303); new = self.cookie(result,SESSION)
        self.assertNotEqual(new,old); self.assertIsNotNone(self.session_row(old)[2])
        self.assertEqual(call(app,self.detail(f),headers=headers)[0],303)
        self.assertEqual(call(app,self.detail(f),headers=self.owner_headers(new))[0],200)
        self.assertEqual(self.admin.execute("SELECT count(*) FROM retail.owner_portal_events WHERE session_sha256=%s AND event_type='login_rotation'",(digest(old),)).fetchone()[0],1)
        self.admin.rollback()
        self.assertEqual(self.bundle_count(f['snapshot']['request']['proposal_id']),(0,0,0))

    def test_auth_05_logout_csrf_commit_then_delete_cookie_and_deny_replay(self):
        app, _, raw = self.signed_in()
        self.assertEqual(self.sign_out(app,raw,'0'*64)[0],403); self.assertIsNone(self.session_row(raw)[2])
        status, _, headers = self.sign_out(app,raw)
        self.assertEqual(status,303); self.assertEqual(dict(headers)[b'location'],b'/portal/login')
        self.assertEqual(self.cookie(headers,SESSION),''); self.assertIsNotNone(self.session_row(raw)[2])
        self.assertEqual(call(app,'/portal',headers=self.owner_headers(raw))[0],303)
        self.assertEqual(self.sign_out(app,raw)[0],401)
        self.assertEqual(self.admin.execute("SELECT count(*) FROM retail.owner_portal_events WHERE session_sha256=%s AND event_type='logout'",(digest(raw),)).fetchone()[0],1)
        self.admin.rollback()

    def test_auth_06_expired_boundary_future_and_manual_revocation_denied(self):
        app = self.app()
        for offset in ("interval '1 hour'", "interval '61 minutes'", "-interval '1 minute'"):
            raw = next(self.browser_pool)
            self.admin.execute('WITH t AS (SELECT statement_timestamp()-('+offset+') AS t) '
                "INSERT INTO retail.owner_portal_sessions SELECT %s,%s,%s,t,t+interval '1 hour',NULL FROM t",
                (digest(raw),self.owner,digest(session_csrf(raw))))
            self.admin.commit()
            self.assertEqual(call(app,'/portal',headers=self.owner_headers(raw))[0],303)
            self.assertEqual(self.sign_out(app,raw)[0],401)
        app, headers, raw = self.signed_in(app)
        self.admin.execute('UPDATE retail.owner_portal_sessions SET revoked_at=clock_timestamp() WHERE session_sha256=%s',(digest(raw),)); self.admin.commit()
        self.assertEqual(call(app,'/portal',headers=headers)[0],303)

    def test_auth_07_wrong_owner_hash_service_token_and_malformed_token_no_session(self):
        app = self.app(); before = self.auth_counts()
        for token in ('0'*64,foundation.CONFIG['owner_hash'],foundation.CONFIG['service_token'],'bad','A'*64):
            status, body, headers = self.sign_in(app,owner=token)
            self.assertEqual(status,401); self.assertIsNone(self.cookie(headers,SESSION))
            self.assertNotIn(token.encode(),body)
        self.assertEqual(self.auth_counts(),before)

    def test_auth_08_challenge_signature_nonce_exclusive_age_and_future(self):
        app = self.app(); nonce, signed = self.challenge(app); before = self.auth_counts()
        base = foundation.CONFIG['auth_clock']; key=bytes.fromhex(foundation.CONFIG['portal_key'])
        for offset in (-300,-301,1):
            unsigned=nonce+'.'+str(base+offset)
            aged=unsigned+'.'+hmac.new(key,unsigned.encode(),'sha256').hexdigest()
            self.assertEqual(self.sign_in(app,challenge=(nonce,aged))[0],403)
        for challenge in ((nonce,signed[:-1]+('0' if signed[-1]!='0' else '1')),('0'*64,signed),(nonce,'bad')):
            self.assertEqual(self.sign_in(app,challenge=challenge)[0],403)
        self.assertEqual(self.auth_counts(),before)

    def test_auth_09_origin_host_duplicate_cookie_token_and_body_guards(self):
        app = self.app(); nonce,signed=self.challenge(app); before=self.auth_counts()
        body=urlencode({'owner_token':foundation.CONFIG['owner_token'],'csrf':nonce}).encode()
        base=[(b'host',b'127.0.0.1:18081'),(b'cookie',(CHALLENGE+'='+signed).encode()),
              (b'origin',b'http://127.0.0.1:18081'),(b'content-type',b'application/x-www-form-urlencoded')]
        for headers,status in (([h for h in base if h[0]!=b'origin'],403),
                ([h for h in base if h[0]!=b'origin']+[(b'origin',b'null')],403),
                (base+[(b'origin',b'https://outside.invalid')],403),
                (base+[(b'cookie',b'x=y')],400),(base+[(b'host',b'localhost:18081')],400),
                (base+[(b'authorization',b'Bearer '+foundation.CONFIG['service_token'].encode())],400)):
            self.assertEqual(call(app,'/portal/login','POST',body,headers=headers)[0],status)
        self.assertEqual(call(app,'/portal/login','POST',body+b'&csrf='+nonce.encode(),headers=base)[0],400)
        self.assertEqual(call(app,'/portal/login','POST',b'x'*2049,headers=base)[0],413)
        self.assertEqual(call(app,'/portal/login','POST',body,headers=base,query=b'x=1')[0],400)
        self.assertEqual(self.auth_counts(),before)

    def test_auth_10_login_before_commit_fault_no_cookie_no_session(self):
        review = self.review_store(lambda: AuthCommitFault(psycopg.connect(**foundation.CONFIG['auth']),False))
        app=self.app(review); before=self.auth_counts()
        status,body,headers=self.sign_in(app)
        self.assertEqual(status,503); self.assertIsNone(self.cookie(headers,SESSION))
        self.assertNotIn(b'location',dict(headers)); self.assertIn(b'No new session cookie',body)
        self.assertEqual(self.auth_counts(),before)

    def test_auth_11_real_login_commit_simulated_ack_loss_no_cookie_or_auto_retry(self):
        app=self.app(self.review_store(lambda: AuthCommitFault(psycopg.connect(**foundation.CONFIG['auth']),True)))
        before=self.auth_counts(); status,body,headers=self.sign_in(app)
        self.assertEqual(status,503); self.assertIsNone(self.cookie(headers,SESSION)); self.assertNotIn(b'location',dict(headers))
        self.assertEqual(self.auth_counts(),(before[0]+1,before[1]+1))
        self.assertEqual(call(self.app(),'/portal',headers=[(b'host',b'127.0.0.1:18081')])[0],303)
        self.signed_in(); self.assertEqual(self.auth_counts(),(before[0]+2,before[1]+2))

    def test_auth_12_logout_before_commit_fault_preserves_session(self):
        app,_,raw=self.signed_in()
        failed=self.app(self.review_store(lambda: AuthCommitFault(psycopg.connect(**foundation.CONFIG['auth']),False)))
        before=self.auth_counts(); status,_,headers=self.sign_out(failed,raw)
        self.assertEqual(status,503); self.assertIsNone(self.cookie(headers,SESSION))
        self.assertIsNone(self.session_row(raw)[2]); self.assertEqual(self.auth_counts(),before)
        self.assertEqual(call(app,'/portal',headers=self.owner_headers(raw))[0],200)

    def test_auth_13_real_logout_commit_simulated_ack_loss_then_get_revoked(self):
        app,_,raw=self.signed_in()
        failed=self.app(self.review_store(lambda: AuthCommitFault(psycopg.connect(**foundation.CONFIG['auth']),True)))
        before=self.auth_counts(); status,_,headers=self.sign_out(failed,raw)
        self.assertEqual(status,503); self.assertIsNone(self.cookie(headers,SESSION))
        self.assertIsNotNone(self.session_row(raw)[2]); self.assertEqual(self.auth_counts(),(before[0],before[1]+1))
        status,_,headers=call(app,'/portal',headers=self.owner_headers(raw))
        self.assertEqual(status,303); self.assertEqual(self.cookie(headers,SESSION),'')

    def test_auth_14_invalid_return_validation_rolls_back_real_login_and_logout(self):
        bad=self.app(self.review_store(lambda: AuthResultFault(psycopg.connect(**foundation.CONFIG['auth']),False)))
        before=self.auth_counts(); status,_,headers=self.sign_in(bad)
        self.assertEqual(status,503); self.assertIsNone(self.cookie(headers,SESSION)); self.assertEqual(self.auth_counts(),before)
        _,_,raw=self.signed_in(); before=self.auth_counts()
        self.assertEqual(self.sign_out(bad,raw)[0],503)
        self.assertIsNone(self.session_row(raw)[2]); self.assertEqual(self.auth_counts(),before)

    def test_auth_15_actual_login_event_fault_rolls_back_rotation(self):
        app,_,old=self.signed_in(); before=self.auth_counts()
        self.admin.execute("CREATE FUNCTION pg_temp.auth_fault_v2() RETURNS trigger LANGUAGE plpgsql AS "
                           "$$ BEGIN RAISE EXCEPTION 'Synthetic audit fault'; END $$")
        self.admin.execute('CREATE TRIGGER auth_test_fault BEFORE INSERT ON retail.owner_portal_events '
                           'FOR EACH ROW EXECUTE FUNCTION pg_temp.auth_fault_v2()'); self.admin.commit()
        try:
            status,_,headers=self.sign_in(app,old=old)
            self.assertEqual(status,503); self.assertIsNone(self.cookie(headers,SESSION))
            self.assertIsNone(self.session_row(old)[2]); self.assertEqual(self.auth_counts(),before)
        finally:
            self.admin.execute('DROP TRIGGER auth_test_fault ON retail.owner_portal_events'); self.admin.commit()

    def test_auth_16_cap_eight_and_rotation_at_cap_retains_absolute_expiry(self):
        app=self.app(); sessions=[]
        for _ in range(8):
            _,_,raw=self.signed_in(app); sessions.append(raw)
        status,_,headers=self.sign_in(app)
        self.assertEqual(status,429); self.assertIsNone(self.cookie(headers,SESSION))
        status,_,headers=self.sign_in(app,old=sessions[0])
        self.assertEqual(status,303); self.assertIsNotNone(self.session_row(sessions[0])[2])
        self.assertEqual(self.admin.execute('SELECT count(*) FROM retail.owner_portal_sessions WHERE reviewer_id=%s '
            'AND revoked_at IS NULL AND expires_at>clock_timestamp()',(self.owner,)).fetchone()[0],8)
        self.admin.rollback()

    def test_auth_17_held_owner_and_session_locks_fail_busy_not_login_success(self):
        app,headers,raw=self.signed_in()
        with psycopg.connect(**foundation.CONFIG['admin']) as lock:
            lock.execute('SELECT 1 FROM retail.owner_credentials WHERE reviewer_id=%s FOR UPDATE',(self.owner,))
            self.assertEqual(call(app,'/portal',headers=headers)[0],429)
            self.assertEqual(self.sign_in(app)[0],429); lock.rollback()
            lock.execute('SELECT 1 FROM retail.owner_portal_sessions WHERE session_sha256=%s FOR UPDATE',(digest(raw),))
            self.assertEqual(call(app,'/portal',headers=headers)[0],429)
            self.assertEqual(self.sign_out(app,raw)[0],429); lock.rollback()
        self.assertEqual(call(app,'/portal',headers=headers)[0],200)

    def test_auth_18_connection_identity_and_five_login_separation_fail_closed(self):
        with self.assertRaises(ValueError):
            IsolatedPortalAuth(self.store('reader'),self.store('reviewer'),self.store('issuer'),self.store('transition'),self.store('reader'))
        app=self.app(self.review_store(lambda: psycopg.connect(**foundation.CONFIG['reader'])))
        before=self.auth_counts(); status,_,headers=self.sign_in(app)
        self.assertEqual(status,503); self.assertIsNone(self.cookie(headers,SESSION)); self.assertEqual(self.auth_counts(),before)

    def test_auth_19_fresh_login_transition_provenance_approval_logout_no_publication(self):
        f=self.legacy_fixture(); value=self.transition(f,'auth-transition-'+uuid4().hex); fresh=self.new_fixture(f,value)
        app,headers,raw=self.signed_in()
        for path in (self.path_evidence(f),self.path_legacy(f),self.detail(fresh)):
            status,body,_=call(app,path,headers=headers)
            self.assertEqual(status,200); self.assertIn(b'Sign out',body)
            self.assertIn(value['transition_sha256'].encode(),body)
        form=self.form(app,fresh,headers)
        self.assertEqual(self.post(app,fresh,headers,form)[0],303)
        self.assertEqual(self.bundle_count(value['transition']['first_request_id']),(1,1,0))
        self.assert_old_preserved(f)
        self.assertEqual(self.sign_out(app,raw)[0],303)
        self.assertEqual(self.post(app,fresh,headers,form)[0],401)

    def test_auth_20_service_bearer_cannot_login_or_owner_cookie_issue(self):
        app,headers,raw=self.signed_in(); case,payload=self.bare_case()
        self.assertEqual(self.issue(app,case,payload,headers=headers+[(b'content-type',b'application/json'),(b'idempotency-key',b'owner-not-service')])[0],401)
        self.assertEqual(self.sign_in(app,owner=foundation.CONFIG['service_token'])[0],401)
        self.assertEqual(call(app,'/portal',headers=[(b'host',b'127.0.0.1:18081'),
            (b'authorization',b'Bearer '+foundation.CONFIG['service_token'].encode())])[0],400)

    def test_auth_21_fresh_clock_denies_session_expiring_during_same_sql_statement(self):
        raw=next(self.browser_pool)
        with psycopg.connect(**foundation.CONFIG['auth']) as conn:
            conn.read_only=False
            # Test-only function has no table rights; records the statement start
            # before sleeping and calls the same fixed scoped identity function.
            conn.execute("CREATE FUNCTION pg_temp.auth_expiry_probe(s text,e timestamptz) RETURNS jsonb "
                "LANGUAGE plpgsql AS $$ DECLARE denied boolean:=false; BEGIN PERFORM pg_sleep(1.2); "
                "BEGIN PERFORM retail.api_portal_auth_identity_v2(s); EXCEPTION WHEN insufficient_privilege THEN denied:=true; END; "
                "RETURN jsonb_build_object('started_in_window',statement_timestamp()<e,'ended_outside',clock_timestamp()>=e,'denied',denied); END $$")
            conn.commit()
            self.admin.execute("WITH t AS (SELECT clock_timestamp()-interval '1 hour'+interval '1 second' AS t) "
                "INSERT INTO retail.owner_portal_sessions SELECT %s,%s,%s,t,t+interval '1 hour',NULL FROM t",
                (digest(raw),self.owner,digest(session_csrf(raw)))); self.admin.commit()
            result=conn.execute('SELECT pg_temp.auth_expiry_probe(%s,%s)',(digest(raw),self.session_row(raw)[1])).fetchone()[0]
            self.assertEqual(result,{'started_in_window':True,'ended_outside':True,'denied':True})

    def test_auth_zz_owner_revocation_denies_old_session_new_login_and_logout(self):
        app,headers,raw=self.signed_in()
        self.admin.execute('UPDATE retail.owner_credentials SET revoked_at=clock_timestamp() WHERE reviewer_id=%s',(self.owner,)); self.admin.commit()
        before=self.auth_counts()
        self.assertEqual(call(app,'/portal',headers=headers)[0],303)
        self.assertEqual(self.sign_in(app)[0],401); self.assertEqual(self.sign_out(app,raw)[0],401)
        self.assertEqual(self.auth_counts(),before)


if __name__=='__main__':
    foundation.CONFIG=json.loads(sys.stdin.read())
    AuthTests.__unittest_skip__=False
    suite=unittest.TestSuite(AuthTests(name) for name in dir(AuthTests) if name.startswith('test_auth_'))
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
