"""Report request ASGI and transaction adapter checks, without a live database."""
import json
import secrets
import threading
import unittest
from unittest.mock import patch
from uuid import UUID

import psycopg
from fastapi import HTTPException
from api.main import CalculationRequest, CaseStore, Settings, create_app
from test_wp2_api import FakeCalculator, call, request_payload

CID = "00000000-0000-0000-0000-000000000013"


def metadata(state="received"):
    return json.dumps({"case_id": CID, "state": state, "revision": 1 if state != "received" else None})


class FakeStore:
    def __init__(self):
        self.calls = []

    def submit(self, key, payload):
        self.calls.append(key)
        return metadata(), 202

    def get(self, cid):
        return metadata("awaiting_approval")

    def revision(self, cid, revision):
        return '{"exact":0.73293010234875627641}'


class CaseRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_authentication_and_header_validation(self):
        settings = Settings(secrets.token_hex(32), "unused")
        store = FakeStore()
        app = create_app(settings, FakeCalculator(), store)
        self.assertEqual((await call(app, path="/api/v1/report-requests", token=None))[0], 401)
        self.assertEqual((await call(app, path="/api/v1/report-requests", token=settings.token))[0], 422)
        self.assertEqual(store.calls, [])
        for key in ("short", "a" * 129, "hostile/key", "valid-key-013"):
            # Reuse ASGI helper while injecting observed request headers in middleware.
            async def keyed(scope, receive, send):
                scope["headers"].append((b"idempotency-key", key.encode()))
                await app(scope, receive, send)
            status, body, headers = await call(keyed, path="/api/v1/report-requests", token=settings.token)
            self.assertEqual(status, 202 if key == "valid-key-013" else 422)
            if status == 202:
                self.assertIn((b"retry-after", b"5"), headers)
                self.assertIn((b"location", ("/api/v1/cases/" + CID).encode()), headers)
        async def duplicated(scope, receive, send):
            scope["headers"].extend([(b"idempotency-key", b"valid-key-013")] * 2)
            await app(scope, receive, send)
        self.assertEqual((await call(duplicated, path="/api/v1/report-requests", token=settings.token))[0], 422)

    async def test_case_and_unapproved_exact_revision_routes(self):
        settings = Settings(secrets.token_hex(32), "unused")
        app = create_app(settings, FakeCalculator(), FakeStore())
        path = "/api/v1/cases/" + CID
        self.assertEqual((await call(app, "GET", path))[0], 401)
        self.assertEqual((await call(app, "GET", path, token=settings.token))[0], 200)
        status, body, headers = await call(app, "GET", path + "/revisions/1", token=settings.token)
        self.assertEqual(status, 200)
        self.assertIn(b"0.73293010234875627641", body)
        self.assertIn((b"x-report-status", b"unapproved-draft"), headers)
        self.assertEqual((await call(app, "GET", "/api/v1/cases/not-uuid", token=settings.token))[0], 422)
        self.assertEqual((await call(app, "GET", "/api/v1/reports/" + CID, token=settings.token))[0], 404)
        schema = json.loads((await call(app, "GET", "/openapi.json", token=settings.token))[1])
        operation = schema["paths"]["/api/v1/report-requests"]["post"]
        self.assertTrue(operation["parameters"][0]["required"])
        self.assertEqual(operation["parameters"][0]["name"], "Idempotency-Key")
        self.assertIn("202", operation["responses"])
        self.assertEqual(operation["security"], [{"CalculationToken": []}])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.slot = threading.BoundedSemaphore(1)
        self.store = CaseStore(Settings(secrets.token_hex(32), "unused", "unused-case"), self.slot)
        self.payload = CalculationRequest(**request_payload())

    def test_replay_skips_calculation_and_busy_reservation_is_returned(self):
        for revision in (-1, 0, 2, 10 ** 100):
            with patch.object(self.store, "query") as query:
                with self.assertRaises(HTTPException) as error:
                    self.store.revision(UUID(CID), revision)
                self.assertEqual(error.exception.status_code, 404)
                query.assert_not_called()
        with patch.object(self.store, "query", return_value=metadata("awaiting_approval")) as query:
            self.assertEqual(self.store.submit("unit-key-013", self.payload)[1], 200)
            self.assertEqual(query.call_count, 1)
        self.slot.acquire()
        with patch.object(self.store, "query", return_value=metadata()) as query:
            self.assertEqual(self.store.submit("unit-key-013", self.payload)[1], 202)
            self.assertEqual(query.call_count, 1)
        self.slot.release()

    def test_failure_returns_recovery_location_and_releases_slot(self):
        with patch.object(self.store, "query", side_effect=[metadata(), HTTPException(504, "Timeout")]):
            with self.assertRaises(HTTPException) as error:
                self.store.submit("unit-key-013", self.payload)
            self.assertEqual(error.exception.headers["Location"], "/api/v1/cases/" + CID)
            self.assertTrue(self.slot.acquire(blocking=False))
            self.slot.release()

    def test_fixed_queries_commit_before_return_and_safe_errors(self):
        calls = []
        class Cursor:
            def __init__(self, row): self.row = row
            def fetchone(self): return self.row
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): calls.append("commit"); return False
            def execute(self, sql, arguments=None):
                calls.append((sql, arguments))
                return Cursor(("raa_wp2_case_api", "raa_wp2_validation") if arguments is None else (metadata(),))
        with patch("api.main.psycopg.connect", return_value=Connection()):
            self.store.get(UUID(CID))
        self.assertEqual(calls[-1], "commit")
        self.assertEqual(calls[1][0], "SELECT retail.api_get_case_v1(%s)")
        for error, status in ((psycopg.errors.UniqueViolation("private"), 409),
                              (psycopg.errors.QueryCanceled("private"), 504),
                              (psycopg.errors.LockNotAvailable("private"), 429),
                              (psycopg.OperationalError("private"), 503)):
            with patch("api.main.psycopg.connect", side_effect=error):
                with self.assertRaises(HTTPException) as result:
                    self.store.get(UUID(CID))
                self.assertEqual(result.exception.status_code, status)
                self.assertNotIn("private", result.exception.detail)


if __name__ == "__main__":
    unittest.main()
