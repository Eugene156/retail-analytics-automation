"""ASGI/model/adapter checks; no authenticated human decision is simulated."""
import json
import secrets
import threading
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
import psycopg
from api.main import ApprovalRequestV2, CaseStore, ProposalRequest, Settings, create_app
from test_wp2_api import FakeCalculator, call

CID = UUID("00000000-0000-0000-0000-000000000015")
HASH = "a" * 64
BODY = {"report_revision": 1, "report_payload_sha256": HASH}
RESPONSE = '{"canonical_payload_text":"immutable fixture","decision_enabled":false,"approved":false,"published":false}'


class FakeStore:
    def __init__(self): self.calls = []
    def prepare_proposal(self, cid, payload):
        self.calls.append((cid, payload.report_revision, payload.report_payload_sha256))
        return RESPONSE
    def proposal(self, cid):
        self.calls.append(cid)
        return RESPONSE


class ProposalRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.token = secrets.token_hex(32)
        self.store = FakeStore()
        self.app = create_app(Settings(self.token, "unused"), FakeCalculator(), self.store)
        self.path = f"/api/v1/cases/{CID}/approval-proposal"

    async def test_service_guard_precedes_parsing_and_no_decision_endpoint(self):
        for method in ("GET", "POST"):
            for token in (None, "wrong"):
                self.assertEqual((await call(self.app, method, self.path, b"{broken", token))[0], 401)
        self.assertEqual(self.store.calls, [])
        self.assertEqual((await call(self.app, "POST", f"/api/v1/cases/{CID}/decision", json.dumps(BODY).encode(), self.token))[0], 404)
        self.assertEqual(self.store.calls, [])

    async def test_strict_preconditions_no_caller_identity_target_or_expiry(self):
        bad_bodies = [{}, {**BODY, "report_revision": True}, {**BODY, "report_revision": 1.0},
                      {**BODY, "report_revision": "1"}, {**BODY, "report_revision": 2},
                      {**BODY, "report_payload_sha256": HASH.upper()}, {**BODY, "report_payload_sha256": None},
                      {**BODY, "report_payload_sha256": "<script>private value</script>"},
                      *({**BODY, name: "private-value"} for name in ("reviewer_id", "target", "ttl_seconds", "expires_at", "approved"))]
        for body in bad_bodies:
            with self.assertRaises(ValidationError): ProposalRequest(**body)
            status, response, _ = await call(self.app, "POST", self.path, json.dumps(body).encode(), self.token)
            self.assertEqual(status, 410)
            self.assertNotIn(b"private", response)
        self.assertEqual(self.store.calls, [])

    async def test_exact_response_no_store_headers_openapi_service_not_reviewer(self):
        for method in ("GET",):
            status, response, headers = await call(self.app, method, self.path, json.dumps(BODY).encode(), self.token)
            self.assertEqual(status, 200)
            self.assertEqual(response, RESPONSE.encode())
            self.assertIn((b"cache-control", b"no-store"), headers)
            self.assertIn((b"x-decision-enabled", b"false"), headers)
        self.assertEqual(self.store.calls[0], CID)
        schema = json.loads((await call(self.app, "GET", "/openapi.json", token=self.token))[1])
        path_schema = schema["paths"]["/api/v1/cases/{case_id}/approval-proposal"]
        for method in ("get", "post"):
            self.assertEqual(path_schema[method]["security"], [{"CalculationToken": []}])
        self.assertIn("410", path_schema["post"]["responses"])
        self.assertTrue(path_schema["post"]["deprecated"])
        self.assertNotIn("/api/v1/cases/{case_id}/decision", schema["paths"])

    async def test_missing_configuration_and_hash_conflict_safe_errors(self):
        for code in (404, 409, 429, 503):
            with patch.object(self.store, "prepare_proposal", side_effect=HTTPException(code, "Safe failure")):
                self.assertEqual((await call(self.app, "POST", self.path, json.dumps(BODY).encode(), self.token))[0], 410)
        self.assertEqual(self.store.calls, [])


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore(Settings(secrets.token_hex(32), "unused", "unused-case"), threading.BoundedSemaphore(1))

    def test_fixed_queries_read_only_retrieval_no_case_calculation(self):
        with patch.object(self.store, "query", return_value=RESPONSE) as query:
            self.assertEqual(self.store.proposal(CID), RESPONSE)
            query.assert_called_once_with("SELECT retail.api_get_approval_proposal_v1(%s)", (CID,), read_only=True)
        self.assertFalse(hasattr(self.store, "prepare_proposal"))
        for operation in (lambda: self.store.proposal(CID),):
            with patch.object(self.store, "query", return_value=None), self.assertRaises(HTTPException) as error:
                operation()
            self.assertEqual(error.exception.status_code, 404)

    def test_unconfigured_policy_safe_mapping_and_commit_before_return(self):
        with patch("api.main.psycopg.connect", side_effect=psycopg.errors.ObjectNotInPrerequisiteState("private configuration")):
            with self.assertRaises(HTTPException) as error:
                self.store.issue_approval_request(CID, "fixture-key-v2", ApprovalRequestV2(**BODY, predecessor_proposal_id=None))
            self.assertEqual(error.exception.status_code, 503)
            self.assertNotIn("private", error.exception.detail)
        operations = []
        class Cursor:
            def __init__(self, value): self.value = value
            def fetchone(self): return self.value
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): operations.append("committed")
            def execute(self, sql, arguments=None):
                operations.append((sql, arguments))
                return Cursor(("raa_wp2_case_api", "raa_wp2_validation") if arguments is None else (RESPONSE,))
        with patch("api.main.psycopg.connect", return_value=Connection()):
            self.assertEqual(self.store.issue_approval_request(CID, "fixture-key-v2", ApprovalRequestV2(**BODY, predecessor_proposal_id=None)), RESPONSE)
        self.assertEqual(operations[-1], "committed")


if __name__ == "__main__":
    unittest.main()
