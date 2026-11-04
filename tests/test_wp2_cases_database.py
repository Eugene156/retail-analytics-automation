"""Opt-in live restricted-login checks; reservations remain as local test evidence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import unittest
from uuid import uuid4

import psycopg
from api.main import SOURCE_HASH, Settings


class CaseDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = Settings.from_environment().case_dsn

    def connect(self):
        return psycopg.connect(self.dsn, connect_timeout=5)

    def reserve(self, key):
        with self.connect() as conn:
            row = conn.execute("SELECT retail.api_reserve_report_v1(%s,%s,%s,%s,%s)",
                (key, SOURCE_HASH, datetime(2011, 1, 28, 9), datetime(2011, 1, 28, 10),
                 datetime(2011, 1, 28, 10))).fetchone()
        return json.loads(row[0])

    def test_restricted_identity_and_direct_access_denied(self):
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT current_user, current_database()").fetchone(),
                             ("raa_wp2_case_api", "raa_wp2_validation"))
            self.assertEqual(conn.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                "FROM pg_roles WHERE rolname=current_user").fetchone(), (False,) * 4)
            for sql in ("SELECT * FROM retail.source_rows LIMIT 1",
                        "SELECT * FROM retail.report_revisions LIMIT 1",
                        "UPDATE retail.report_cases SET state='received'",
                        "CREATE TABLE retail.unauthorized_test(id integer)"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(sql)
                conn.rollback()

    def test_ten_concurrent_reservations_have_one_case_and_event(self):
        key = "db-race-" + uuid4().hex
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(self.reserve, [key] * 10))
        self.assertEqual(len({row["case_id"] for row in results}), 1)
        self.assertTrue(all(row == results[0] for row in results))
        self.assertEqual(len(results[0]["audit_events"]), 1)

    def test_sql_timeout_after_durable_reservation_preserves_received(self):
        case = self.reserve("db-timeout-" + uuid4().hex)
        with self.connect() as conn:
            conn.execute("SET LOCAL statement_timeout='50ms'")
            with self.assertRaises(psycopg.errors.QueryCanceled):
                conn.execute("SELECT retail.api_finish_report_v1(%s)", (case["case_id"],))
            conn.rollback()
            after = json.loads(conn.execute("SELECT retail.api_get_case_v1(%s)", (case["case_id"],)).fetchone()[0])
            self.assertEqual(after, case)
            self.assertIsNone(conn.execute("SELECT retail.api_get_revision_v1(%s,1)", (case["case_id"],)).fetchone()[0])

    def test_database_row_lock_blocks_second_finisher_without_duplicate(self):
        case = self.reserve("db-lock-" + uuid4().hex)
        with self.connect() as first, self.connect() as second:
            # A tiny timeout bounds the expensive report while the first row lock
            # is proven through an actual concurrent fixed-function call.
            first.execute("SET LOCAL statement_timeout='2000ms'")
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(first.execute, "SELECT retail.api_finish_report_v1(%s)", (case["case_id"],))
                import time
                observed = False
                for _ in range(20):
                    active = second.execute("SELECT state='active' AND query LIKE "
                        "'SELECT retail.api_finish_report_v1%%' FROM pg_stat_activity WHERE pid=%s",
                        (first.info.backend_pid,)).fetchone()
                    if active == (True,):
                        time.sleep(0.05)
                        with self.assertRaises(psycopg.errors.LockNotAvailable):
                            second.execute("SELECT retail.api_finish_report_v1(%s)", (case["case_id"],))
                        second.rollback()
                        observed = True
                        break
                    second.commit()  # Refresh pg_stat_activity's statistics snapshot.
                    time.sleep(0.02)
                self.assertTrue(observed)
                with self.assertRaises(psycopg.errors.QueryCanceled):
                    pending.result(timeout=5)
            first.rollback()
            after = json.loads(second.execute("SELECT retail.api_get_case_v1(%s)", (case["case_id"],)).fetchone()[0])
            self.assertEqual(after, case)


if __name__ == "__main__":
    unittest.main()
