"""Actual legacy read / retired-write rights after migration 017."""
import unittest
import psycopg
from api.main import Settings

CASE_ID = "61b10574-c842-4dae-8e8b-647f0d51ba55"
HASH = "2e913def90e1a5e41f9ac6009dd49b7411a8e703d936cdc6b7e5f7a95ed12b07"


class ProposalDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.dsn = Settings.from_environment().case_dsn

    def test_actual_role_fixed_rights_and_direct_access_denied(self):
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            self.assertEqual(conn.execute("SELECT current_user,current_database()").fetchone(), ("raa_wp2_case_api", "raa_wp2_validation"))
            for function, expected in (("retail.api_get_approval_proposal_v1(uuid)",True),
                                       ("retail.api_prepare_approval_proposal_v1(uuid,integer,text)",False)):
                self.assertEqual(conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')", (function,)).fetchone(), (expected,))
            for sql in ("SELECT * FROM retail.approval_policies", "SELECT * FROM retail.approval_proposals",
                        "SELECT * FROM retail.proposal_audit_events", "UPDATE retail.approval_policies SET ttl_seconds=60",
                        "DELETE FROM retail.approval_proposals", "CREATE TABLE retail.unauthorized_proposal_test(id integer)"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): conn.execute(sql)
                conn.rollback()

    def test_retired_preparation_denied_without_case_change(self):
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            before = conn.execute("SELECT retail.api_get_case_v1(%s)", (CASE_ID,)).fetchone()[0]
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT retail.api_prepare_approval_proposal_v1(%s,1,%s)", (CASE_ID,HASH))
            conn.rollback()
            self.assertEqual(conn.execute("SELECT retail.api_get_case_v1(%s)", (CASE_ID,)).fetchone()[0], before)
            self.assertIsNone(conn.execute("SELECT retail.api_get_approval_proposal_v1(%s)", (CASE_ID,)).fetchone()[0])

    def test_read_only_get_and_invalid_arguments(self):
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            conn.read_only = True
            self.assertIsNone(conn.execute("SELECT retail.api_get_approval_proposal_v1(%s)", (CASE_ID,)).fetchone()[0])
            conn.commit()
            for version, digest in ((2,HASH),(1,None),(1,"invalid")):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute("SELECT retail.api_prepare_approval_proposal_v1(%s,%s,%s)", (CASE_ID,version,digest))
                conn.rollback()


if __name__ == "__main__": unittest.main()
