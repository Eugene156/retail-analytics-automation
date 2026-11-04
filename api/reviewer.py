"""Separate owner bearer authentication and fixed read-only database adapter.

This is not a browser login/session or an approval credential. Only token
digests reach PostgreSQL; server-side rows establish identity on every request.
"""
from hashlib import sha256
import re
from uuid import UUID

import psycopg
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool


class ReviewerStore:
    def __init__(self, dsn):
        self.dsn = dsn

    def query(self, sql, arguments):
        if not self.dsn:
            raise HTTPException(503, "Reviewer access is unavailable")
        try:
            with psycopg.connect(self.dsn, connect_timeout=5,
                    options="-c statement_timeout=5000 -c default_transaction_read_only=on -c timezone=UTC") as conn:
                conn.read_only = True
                if conn.execute("SELECT current_user,current_database()").fetchone() != (
                        "raa_wp4_reviewer_api", "raa_wp2_validation"):
                    raise HTTPException(503, "Reviewer access is unavailable")
                return conn.execute(sql, arguments).fetchone()[0]
        except psycopg.errors.InsufficientPrivilege:
            raise HTTPException(401, "Unauthorized") from None
        except psycopg.Error:
            raise HTTPException(503, "Reviewer access is unavailable") from None

    def identity(self, digest):
        value = self.query("SELECT retail.api_owner_identity_v1(%s)", (digest,))
        if value is None:
            raise HTTPException(401, "Unauthorized")
        return UUID(str(value))

    def get(self, digest, case_id):
        return self.required("SELECT retail.api_owner_case_v1(%s,%s)", (digest, case_id))

    def revision(self, digest, case_id, revision):
        if revision != 1:
            raise HTTPException(404, "Draft not found")
        return self.required("SELECT retail.api_owner_revision_v1(%s,%s,%s)", (digest, case_id, revision))

    def proposal(self, digest, case_id):
        return self.required("SELECT retail.api_owner_proposal_v1(%s,%s)", (digest, case_id))

    def approval_request(self, digest, case_id, proposal_id=None):
        if proposal_id is None:
            return self.required("SELECT retail.api_owner_current_request_v2(%s,%s)", (digest, case_id))
        return self.required("SELECT retail.api_owner_approval_request_v2(%s,%s,%s)", (digest, case_id, proposal_id))

    def required(self, sql, arguments):
        value = self.query(sql, arguments)
        if value is None:
            raise HTTPException(404, "Review object not found")
        return value


class ReviewerGuard:
    def __init__(self, app, store):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/review/"):
            return await self.app(scope, receive, send)
        original_send = send

        async def private_send(message):
            if message["type"] == "http.response.start":
                response_headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                message = {**message, "headers": response_headers + [(b"cache-control", b"no-store")]}
            await original_send(message)

        send = private_send
        headers = {"Cache-Control": "no-store", "WWW-Authenticate": "Bearer"}
        values = [v for k, v in scope["headers"] if k.lower() == b"authorization"]
        if len(values) != 1 or not re.fullmatch(rb"Bearer [a-f0-9]{64}", values[0]):
            return await JSONResponse({"detail": "Unauthorized"}, 401, headers=headers)(scope, receive, send)
        digest = sha256(values[0][7:]).hexdigest()
        try:
            identity = await run_in_threadpool(self.store.identity, digest)
        except HTTPException as error:
            return await JSONResponse({"detail": error.detail}, error.status_code,
                                      headers=headers)(scope, receive, send)
        scope.setdefault("state", {}).update(reviewer_digest=digest, reviewer_id=identity)
        if scope["method"] != "GET":
            return await JSONResponse({"detail": "Reviewer access is read-only"}, 405,
                headers={"Allow": "GET", "Cache-Control": "no-store"})(scope, receive, send)
        # No cookies, sessions, CORS allowance or URL credentials are accepted.
        return await self.app(scope, receive, send)
