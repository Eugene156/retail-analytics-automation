"""Synthetic ASGI and adapter tests, not evidence of owner sign-in/approval."""
from hashlib import sha256
import json
import secrets
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException
import psycopg
from api.main import Settings, create_app
from api.reviewer import ReviewerStore
from test_wp2_api import FakeCalculator, call
from test_wp3_preview import CID, fixture, encoded

OWNER = UUID(int=16)


class FakeReviewer:
    def __init__(self, token):
        self.digest = sha256(token.encode()).hexdigest()
        self.calls, self.revoked = [], False
        self.metadata, self.payload = encoded(*fixture())

    def identity(self, digest):
        self.calls.append(("identity", digest))
        if digest != self.digest or self.revoked:
            raise HTTPException(401, "Unauthorized")
        return OWNER

    def get(self, digest, case_id):
        self.calls.append(("get", digest, case_id))
        return self.metadata

    def revision(self, digest, case_id, revision):
        if revision != 1:
            raise HTTPException(404, "Draft not found")
        self.calls.append(("revision", digest, case_id, revision))
        return self.payload

    def proposal(self, digest, case_id):
        self.calls.append(("proposal", digest, case_id))
        raise HTTPException(404, "Review object not found")


class ReviewerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service, self.owner = secrets.token_hex(32), secrets.token_hex(32)
        self.store = FakeReviewer(self.owner)
        self.app = create_app(Settings(self.service, "unused"), FakeCalculator(), reviewer_store=self.store)

    async def test_missing_wrong_service_duplicate_cookies_and_query_fail_closed(self):
        for token, duplicate in ((None,False),("wrong",False),(self.service,False),(self.owner,True)):
            status, body, headers = await call(self.app, "POST", "/review/v1/identity", b"{broken", token, duplicate)
            self.assertEqual(status, 401)
            self.assertNotIn(self.owner.encode(), body)
            self.assertIn((b"cache-control",b"no-store"), headers)
        result = await call(self.app, "GET", "/review/v1/identity", extra_headers=[
            (b"cookie", ("token="+self.owner).encode())], query_string=("token="+self.owner).encode())
        self.assertEqual(result[0], 401)

    async def test_identity_server_mapped_and_digest_only(self):
        status, body, headers = await call(self.app,"GET","/review/v1/identity",token=self.owner)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body), {"reviewer_id":str(OWNER),"access":"read-only",
            "approval_ttl_seconds":86400,"decision_enabled":False,"published":False})
        self.assertEqual(self.store.calls,[("identity",sha256(self.owner.encode()).hexdigest())])
        self.assertNotIn(self.owner.encode(),body)
        self.assertIn((b"x-decision-enabled",b"false"),headers)

    async def test_owner_cannot_use_service_routes_or_mutating_methods(self):
        for path in ("/api/v1/cases/"+str(CID),"/readyz","/openapi.json"):
            self.assertEqual((await call(self.app,"GET",path,token=self.owner))[0],401)
        for method in ("POST","PUT","DELETE","PATCH","HEAD","OPTIONS"):
            self.assertEqual((await call(self.app,method,"/review/v1/cases/"+str(CID)+"/decision",token=self.owner))[0],405)
        self.assertEqual((await call(self.app,"GET","/review/v1/cases/"+str(CID)+"/decision",token=self.owner))[0],404)

    async def test_preview_case_and_schema_scoped_to_owner(self):
        base = "/review/v1/cases/"+str(CID)
        self.assertEqual((await call(self.app,"GET",base,token=self.owner))[1],self.store.metadata.encode())
        status,body,headers = await call(self.app,"GET",base+"/revisions/1/preview",token=self.owner)
        self.assertEqual(status,200)
        self.assertIn(b"UNAPPROVED DRAFT",body)
        self.assertIn((b"x-report-status",b"unapproved-draft"),headers)
        self.assertEqual((await call(self.app,"GET",base+"/revisions/2/preview",token=self.owner))[0],404)
        self.assertEqual((await call(self.app,"GET",base+"/approval-proposal",token=self.owner))[0],404)
        schema = json.loads((await call(self.app,"GET","/openapi.json",token=self.service))[1])
        for path, methods in schema["paths"].items():
            if path.startswith("/review/"):
                self.assertEqual(methods["get"]["security"],[{"OwnerReadToken":[]}])

    async def test_revoked_or_unavailable_identity_never_reaches_reader(self):
        self.store.revoked = True
        self.assertEqual((await call(self.app,"GET","/review/v1/cases/"+str(CID),token=self.owner))[0],401)
        self.assertTrue(all(c[0]=="identity" for c in self.store.calls))
        with patch.object(self.store,"identity",side_effect=HTTPException(503,"Reviewer access is unavailable")):
            self.assertEqual((await call(self.app,"GET","/review/v1/identity",token=self.owner))[0],503)


class ReviewerAdapterTests(unittest.TestCase):
    def test_fixed_read_functions_and_safe_denials(self):
        store = ReviewerStore("unused")
        digest = "a"*64
        with patch.object(store,"query",return_value=str(OWNER)) as query:
            self.assertEqual(store.identity(digest),OWNER)
            query.assert_called_once_with("SELECT retail.api_owner_identity_v1(%s)",(digest,))
        with patch.object(store,"query",return_value="exact") as query:
            self.assertEqual(store.revision(digest,CID,1),"exact")
            query.assert_called_once_with("SELECT retail.api_owner_revision_v1(%s,%s,%s)",(digest,CID,1))
        for error, code in ((psycopg.errors.InsufficientPrivilege("private"),401),
                            (psycopg.OperationalError("private connection"),503)):
            with patch("api.reviewer.psycopg.connect",side_effect=error), self.assertRaises(HTTPException) as result:
                store.identity(digest)
            self.assertEqual(result.exception.status_code,code)
            self.assertNotIn("private",result.exception.detail)
        with self.assertRaises(HTTPException) as result:
            ReviewerStore(None).identity(digest)
        self.assertEqual(result.exception.status_code,503)

    def test_transaction_read_only_and_database_role_identity(self):
        class Cursor:
            def __init__(self,value): self.value=value
            def fetchone(self): return self.value
        class Connection:
            read_only=False
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self,sql,args=None):
                return Cursor(("raa_wp4_reviewer_api","raa_wp2_validation") if args is None else (OWNER,))
        conn=Connection()
        with patch("api.reviewer.psycopg.connect",return_value=conn) as connect:
            self.assertEqual(ReviewerStore("unused").identity("a"*64),OWNER)
            self.assertTrue(conn.read_only)
            self.assertIn("default_transaction_read_only=on",connect.call_args.kwargs["options"])


if __name__ == "__main__": unittest.main()
