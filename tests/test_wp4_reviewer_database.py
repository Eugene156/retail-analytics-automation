"""Opt-in actual reviewer-login checks. Private identity/digest arrive by stdin."""
import json
import os
import sys
import unittest

import psycopg
from api.main import Settings

CASE = "61b10574-c842-4dae-8e8b-647f0d51ba55"


@unittest.skipUnless(os.environ.get("RAA_RUN_REVIEWER_DB_TESTS") == "1", "Opt-in private stdin required")
class ReviewerDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret = json.loads(sys.stdin.read())
        cls.dsn = Settings.from_environment().reviewer_dsn

    def connect(self):
        return psycopg.connect(self.dsn, connect_timeout=5)

    def test_actual_login_read_only_and_fixed_rights(self):
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT current_user,current_database()").fetchone(),
                             ("raa_wp4_reviewer_api", "raa_wp2_validation"))
            self.assertEqual(conn.execute("SHOW transaction_read_only").fetchone(), ("on",))
            for function in ("retail.api_owner_identity_v1(text)", "retail.api_owner_case_v1(text,uuid)",
                             "retail.api_owner_revision_v1(text,uuid,integer)", "retail.api_owner_proposal_v1(text,uuid)"):
                self.assertTrue(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')",(function,)).fetchone()[0])
            for function in ("retail.api_prepare_approval_proposal_v1(uuid,integer,text)",
                             "retail.api_get_case_v1(uuid)", "retail.api_finish_report_v1(uuid)"):
                self.assertFalse(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')",(function,)).fetchone()[0])
            for table in ("retail.owner_credentials", "retail.approval_policies", "retail.report_cases"):
                self.assertFalse(conn.execute("SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE,DELETE')",(table,)).fetchone()[0])
            for sql in ("SELECT * FROM retail.owner_credentials", "SELECT retail.api_get_case_v1(gen_random_uuid())",
                        "SELECT retail.api_prepare_approval_proposal_v1(gen_random_uuid(),1,repeat('a',64))"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): conn.execute(sql)
                conn.rollback()

    def test_actual_server_identity_and_unknown_digest_denial(self):
        with self.connect() as conn:
            identity = conn.execute("SELECT retail.api_owner_identity_v1(%s)",(self.secret["digest"],)).fetchone()[0]
            # Avoid unittest printing credential digests on a failed comparison.
            self.assertTrue(str(identity) == self.secret["reviewer_id"], "Server mapping mismatch")
            self.assertIsNone(conn.execute("SELECT retail.api_owner_identity_v1(%s)",("invalid",)).fetchone()[0])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT retail.api_owner_case_v1(%s,%s)",("invalid",CASE))
            conn.rollback()

    def test_actual_stored_case_revision_and_absent_proposal_reads(self):
        with self.connect() as conn:
            digest = self.secret["digest"]
            case = json.loads(conn.execute("SELECT retail.api_owner_case_v1(%s,%s)",(digest,CASE)).fetchone()[0])
            payload = conn.execute("SELECT retail.api_owner_revision_v1(%s,%s,1)",(digest,CASE)).fetchone()[0]
            self.assertFalse(case["approved"])
            self.assertFalse(case["published"])
            from hashlib import sha256
            self.assertTrue(sha256(payload.encode()).hexdigest() == case["payload_sha256"], "Stored bytes mismatch")
            self.assertIsNone(conn.execute("SELECT retail.api_owner_proposal_v1(%s,%s)",(digest,CASE)).fetchone()[0])


if __name__ == "__main__": unittest.main()
