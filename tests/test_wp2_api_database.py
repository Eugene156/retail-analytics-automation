"""Opt-in live tests inside raa-wp2-api against its restricted login role."""
import unittest
import psycopg
from api.main import Calculator, Settings


class LiveDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.calculator = Calculator(Settings.from_environment())

    def test_dedicated_login_and_read_only_transaction(self):
        with self.calculator.connect() as conn:
            self.calculator.check_identity(conn)
            self.assertEqual(conn.execute("SHOW transaction_read_only").fetchone(), ("on",))
            flags = conn.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                                 "FROM pg_roles WHERE rolname=current_user").fetchone()
            self.assertEqual(flags, (False, False, False, False))

    def test_raw_read_and_direct_dml_are_denied(self):
        for query in ("SELECT count(*) FROM retail.source_rows",
                      "DELETE FROM retail.invoice_lines WHERE false",
                      "CREATE TABLE retail.api_privilege_probe(id integer)"):
            with self.subTest(query=query):
                with self.assertRaises((psycopg.errors.InsufficientPrivilege,
                                        psycopg.errors.ReadOnlySqlTransaction)):
                    with self.calculator.connect() as conn:
                        conn.execute(query)

    def test_database_timeout_cancels_without_fact_mutation(self):
        with self.assertRaises(psycopg.errors.QueryCanceled):
            with self.calculator.connect() as conn:
                conn.execute("SET LOCAL statement_timeout = '50ms'")
                conn.execute("SELECT pg_sleep(0.2)")


if __name__ == "__main__":
    unittest.main()
