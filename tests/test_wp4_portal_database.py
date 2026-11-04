"""Opt-in actual restricted-login tests. Owner digest arrives privately by stdin."""
from hashlib import sha256
import json
import os
import secrets
import sys
import unittest
import psycopg
from api.main import Settings


@unittest.skipUnless(os.environ.get('RAA_RUN_PORTAL_DB_TESTS')=='1','Private stdin and configured DB required')
class PortalDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner=json.loads(sys.stdin.read())
        cls.dsn=Settings.from_environment().portal_dsn

    def test_actual_scoped_login_fixed_rights(self):
        with psycopg.connect(self.dsn,connect_timeout=5) as conn:
            self.assertEqual(conn.execute('SELECT current_user,current_database()').fetchone(),
                ('raa_wp4_portal_api','raa_wp2_validation'))
            self.assertEqual(conn.execute('SHOW transaction_read_only').fetchone(),('on',))
            for fn in ('identity_v1(text)','login_v1(text,text,text,text)','logout_v1(text,text)',
                       'requests_v1(text)','request_v1(text,uuid,uuid)','case_v1(text,uuid)','revision_v1(text,uuid,integer)'):
                self.assertTrue(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')",
                    ('retail.api_portal_'+fn,)).fetchone()[0])
            self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,"
                "'retail.api_issue_approval_request_v2(uuid,integer,text,text,uuid)','EXECUTE')").fetchone()[0])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('SELECT * FROM retail.owner_credentials')
            conn.rollback()

    def test_login_read_logout_fully_rolled_back(self):
        session=sha256(secrets.token_bytes(32)).hexdigest()
        csrf=sha256(secrets.token_bytes(32)).hexdigest()
        with psycopg.connect(self.dsn,connect_timeout=5) as conn:
            conn.read_only=False
            identity=conn.execute('SELECT retail.api_portal_login_v1(%s,%s,%s,NULL)',
                (self.owner['digest'],session,csrf)).fetchone()[0]
            self.assertEqual(str(identity),self.owner['reviewer_id'])
            self.assertEqual(conn.execute('SELECT retail.api_portal_identity_v1(%s)',(session,)).fetchone()[0],identity)
            self.assertIsInstance(json.loads(conn.execute('SELECT retail.api_portal_requests_v1(%s)',(session,)).fetchone()[0]),list)
            self.assertTrue(conn.execute('SELECT retail.api_portal_logout_v1(%s,%s)',(session,csrf)).fetchone()[0])
            self.assertIsNone(conn.execute('SELECT retail.api_portal_identity_v1(%s)',(session,)).fetchone()[0])
            conn.rollback()

    def test_service_token_digest_denied(self):
        with psycopg.connect(self.dsn,connect_timeout=5) as conn:
            conn.read_only=False
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('SELECT retail.api_portal_login_v1(%s,%s,%s,NULL)',
                    (self.owner['service_digest'],'a'*64,'b'*64))
            conn.rollback()
