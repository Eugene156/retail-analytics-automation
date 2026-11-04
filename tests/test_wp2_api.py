"""ASGI/contract/adapter unit tests; not live database evidence."""
import json
import secrets
import unittest
from unittest.mock import patch

import psycopg
from fastapi import HTTPException
from api.main import CalculationRequest, Calculator, QUERY, SOURCE_HASH, Settings, create_app


def request_payload():
    return {"source_file_sha256": SOURCE_HASH,
            "source_time_interpretation": "Europe/London-assumed",
            "period_start_inclusive": "2011-01-28T09:00:00Z",
            "period_end_exclusive": "2011-01-28T10:00:00Z",
            "source_as_of_exclusive": "2011-01-28T10:00:00Z"}


class FakeCalculator:
    calls = 0

    def calculate(self, payload):
        self.calls += 1
        return '{"money": 1349.45, "ratio": 0.73293010234875627641}'

    def ready(self):
        pass


async def call(app, method="POST", path="/api/v1/calculations/comparison", body=None, token=None, duplicate=False,
               extra_headers=None, query_string=b""):
    headers = [(b"content-type", b"application/json")]
    if token is not None:
        headers.append((b"authorization", ("Bearer " + token).encode()))
        if duplicate:
            headers.append(headers[-1])
    headers.extend(extra_headers or [])
    if body is None:
        body = json.dumps(request_payload()).encode()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "root_path": "", "query_string": query_string, "headers": headers,
             "server": ("localhost", 8000), "client": ("localhost", 12345)}
    messages = []
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages[0]["status"], b"".join(m.get("body", b"") for m in messages[1:]), messages[0]["headers"]


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings(secrets.token_hex(32), "unused-test-dsn")
        self.calculator = FakeCalculator()
        self.app = create_app(self.settings, self.calculator)

    async def test_authentication_precedes_parsing_and_rejects_duplicates(self):
        for token, duplicate in ((None, False), ("wrong", False), ("юникод", False),
                                 (self.settings.token, True)):
            status, body, headers = await call(self.app, body=b"{broken", token=token, duplicate=duplicate)
            self.assertEqual(status, 401)
            self.assertEqual(json.loads(body), {"detail": "Unauthorized"})
        self.assertEqual(self.calculator.calls, 0)

    async def test_body_bound_and_validation_do_not_echo_inputs(self):
        status, body, _ = await call(self.app, body=b"x" * 8193, token=self.settings.token)
        self.assertEqual(status, 413)
        for field, value in (("period_start_inclusive", "2011-01-28T09:00:00"),
                             ("period_end_exclusive", "2011-01-28T09:00:00Z"),
                             ("source_as_of_exclusive", "2011-01-28T09:30:00Z"),
                             ("source_file_sha256", "wrong"),
                             ("source_time_interpretation", "UTC"),
                             ("period_start_inclusive", 123456789),
                             ("period_start_inclusive", "0001-01-01T00:00:00Z"),
                             ("period_start_inclusive", "9999-12-31T23:59:59Z")):
            payload = dict(request_payload(), **{field: value})
            status, body, _ = await call(self.app, body=json.dumps(payload).encode(), token=self.settings.token)
            self.assertEqual(status, 422)
            self.assertEqual(json.loads(body), {"detail": "Invalid calculation request"})
        payload = dict(request_payload(), secret="must-not-be-echoed", sql="DROP TABLE retail.source_rows")
        status, body, _ = await call(self.app, body=json.dumps(payload).encode(), token=self.settings.token)
        self.assertEqual(status, 422)
        self.assertNotIn(b"must-not-be-echoed", body)
        self.assertEqual(self.calculator.calls, 0)

    async def test_exact_response_and_authenticated_openapi(self):
        status, body, headers = await call(self.app, token=self.settings.token)
        self.assertEqual(status, 200)
        self.assertIn(b"0.73293010234875627641", body)
        self.assertIn((b"content-type", b"application/json"), headers)
        status, body, _ = await call(self.app, "GET", "/openapi.json", token=self.settings.token)
        self.assertEqual(status, 200)
        schema = json.loads(body)
        operation = schema["paths"]["/api/v1/calculations/comparison"]["post"]
        self.assertEqual(operation["security"], [{"CalculationToken": []}])
        self.assertIn("CalculationRequest", schema["components"]["schemas"])
        status, _, _ = await call(self.app, "GET", "/healthz")
        self.assertEqual(status, 200)
        status, _, _ = await call(self.app, "GET", "/readyz")
        self.assertEqual(status, 401)


class ContractAndAdapterTests(unittest.TestCase):
    def test_timezone_acknowledgement_and_dst_rejection(self):
        summer = dict(request_payload(), period_start_inclusive="2011-05-08T14:00:00Z",
                      period_end_exclusive="2011-05-08T15:00:00Z", source_as_of_exclusive="2011-05-08T15:00:00Z")
        self.assertEqual(CalculationRequest(**summer).source_arguments()[0].hour, 15)
        for start, end in (("2011-10-30T01:30:00+01:00", "2011-10-30T02:30:00Z"),
                           ("2011-03-27T00:00:00Z", "2011-03-27T03:00:00+01:00"),
                           ("2011-04-03T01:30:00+01:00", "2011-04-03T02:30:00+01:00")):
            with self.assertRaises(ValueError):
                CalculationRequest(**dict(request_payload(), period_start_inclusive=start,
                    period_end_exclusive=end, source_as_of_exclusive=end))

    def test_busy_and_safe_database_errors_release_slot(self):
        calculator = Calculator(Settings(secrets.token_hex(32), "unused-test-dsn"))
        payload = CalculationRequest(**request_payload())
        calculator.slot.acquire()
        with self.assertRaises(HTTPException) as result:
            calculator.calculate(payload)
        self.assertEqual(result.exception.status_code, 429)
        calculator.slot.release()
        for error, expected in ((psycopg.errors.QueryCanceled("private-dsn"), 504),
                                (psycopg.errors.InvalidParameterValue("private-dsn"), 422),
                                (psycopg.errors.RaiseException("private-row"), 409),
                                (psycopg.OperationalError("private-password"), 503)):
            with patch("api.main.psycopg.connect", side_effect=error):
                with self.assertRaises(HTTPException) as result:
                    calculator.calculate(payload)
                self.assertEqual(result.exception.status_code, expected)
                self.assertNotIn("private", result.exception.detail)
                self.assertTrue(calculator.slot.acquire(blocking=False))
                calculator.slot.release()

    def test_fixed_parameterized_read_only_query(self):
        class Cursor:
            def __init__(self, result):
                self.result = result
            def fetchone(self):
                return self.result
        class Connection:
            def __init__(self):
                self.calls = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, query, parameters=None):
                self.calls.append((query, parameters))
                return Cursor(("raa_wp2_api", "raa_wp2_validation") if parameters is None else ('{"exact": 1.25}',))
        conn = Connection()
        calculator = Calculator(Settings(secrets.token_hex(32), "unused-test-dsn"))
        with patch("api.main.psycopg.connect", return_value=conn):
            self.assertEqual(calculator.calculate(CalculationRequest(**request_payload())), '{"exact": 1.25}')
        self.assertTrue(conn.read_only)
        self.assertEqual(conn.calls[1][0], QUERY)
        self.assertEqual(conn.calls[1][1][0], SOURCE_HASH)
        self.assertIsNone(conn.calls[1][1][1].tzinfo)


if __name__ == "__main__":
    unittest.main()
