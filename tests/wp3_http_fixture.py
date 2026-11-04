"""Private HTTP fault fixture, NOT application functionality/release evidence.

Only a fixed completed M02 case can be forwarded. No public port or arbitrary URL.
"""
import json
import os
from pathlib import Path
import secrets
import time
from typing import Literal
from urllib.error import HTTPError
from urllib.request import Request as HttpRequest, urlopen
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
import uvicorn

BASE = "http://raa-wp2-api:8000"
HASH = "BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980"
EXPECTED = {"source_file_sha256": HASH, "source_time_interpretation": "Europe/London-assumed",
    "period_start_inclusive": "2011-01-28T09:00:00Z", "period_end_exclusive": "2011-01-28T10:00:00Z",
    "source_as_of_exclusive": "2011-01-28T10:00:00Z"}


class Mode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["retry_503", "pending_202", "exhaust_503", "permanent_401", "corrupt_draft", "swap_identity"]


def application():
    token = Path("/run/secrets/token").read_text().strip()
    cid = str(UUID(os.environ["RAA_WP3_FIXTURE_CASE_ID"]))
    case_path = "/api/v1/cases/" + cid
    state = {"scenario": "retry_503", "calls": [], "started": time.monotonic()}
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    def authorize(request):
        values = request.headers.getlist("authorization")
        if len(values) != 1 or not secrets.compare_digest(values[0], "Bearer " + token):
            raise HTTPException(401, "Unauthorized")

    def upstream(method, path, body=None):
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if method == "POST":
            headers["Idempotency-Key"] = "wp3-manual-m02-v1"
        request = HttpRequest(BASE + path, method=method, headers=headers, data=body)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), {k.lower(): v for k, v in response.headers.items()}

    def observed(method, status):
        state["calls"].append({"method": method, "status": status, "seconds": time.monotonic() - state["started"]})

    @app.post("/__test/configure")
    def configure(mode: Mode, request: Request):
        authorize(request)
        state.update(scenario=mode.scenario, calls=[], started=time.monotonic())
        return {"status": "configured"}

    @app.get("/__test/observations")
    def observations(request: Request):
        authorize(request)
        return {"scenario": state["scenario"], "calls": state["calls"]}

    @app.post("/api/v1/report-requests")
    async def submit(request: Request):
        authorize(request)
        body = await request.body()
        if len(body) > 8192 or request.headers.getlist("idempotency-key") != ["wp3-manual-m02-v1"]:
            raise HTTPException(422, "Fixture request mismatch")
        try:
            if json.loads(body) != EXPECTED:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Fixture request mismatch") from None
        scenario = state["scenario"]
        attempt = sum(call["method"] == "POST" for call in state["calls"]) + 1
        if scenario == "permanent_401":
            observed("POST", 401)
            return Response('{"detail":"Fixture permanent denial"}', status_code=401, media_type="application/json")
        if scenario == "exhaust_503" or (scenario == "retry_503" and attempt == 1):
            observed("POST", 503)
            return Response('{"detail":"Fixture temporary unavailability"}', status_code=503,
                            media_type="application/json", headers={"Retry-After": "2" if scenario == "retry_503" else "1"})
        if scenario == "pending_202" and attempt == 1:
            status, data, headers = upstream("GET", case_path)
            if status != 200:
                raise HTTPException(503, "Fixture prerequisite unavailable")
            pending = json.loads(data)
            pending.update(state="received", revision=None, payload_sha256=None, schema_version=None)
            observed("POST", 202)
            return Response(json.dumps(pending), status_code=202, media_type="application/json", headers={"Retry-After": "2"})
        status, data, headers = upstream("POST", "/api/v1/report-requests", body)
        if scenario == "swap_identity" and status == 200:
            changed = json.loads(data)
            changed["request"]["source_file_sha256"] = "wrong"
            data = json.dumps(changed).encode()
        observed("POST", status)
        return Response(data, status_code=status, media_type="application/json")

    @app.get("/api/v1/cases/{case_id}")
    def get_case(case_id: str, request: Request):
        authorize(request)
        if case_id != cid:
            raise HTTPException(404, "Fixture case not allowed")
        status, data, headers = upstream("GET", case_path)
        observed("GET-case", status)
        return Response(data, status_code=status, media_type="application/json")

    @app.get("/api/v1/cases/{case_id}/revisions/1")
    def get_draft(case_id: str, request: Request):
        authorize(request)
        if case_id != cid:
            raise HTTPException(404, "Fixture case not allowed")
        status, data, headers = upstream("GET", case_path + "/revisions/1")
        if state["scenario"] == "corrupt_draft" and status == 200:
            data += b"\n"
        observed("GET-draft", status)
        return Response(data, status_code=status, media_type="application/json", headers={
            "X-Report-Status": headers.get("x-report-status", "unknown"),
            "X-Source-Time-Interpretation": headers.get("x-source-time-interpretation", "unknown")})

    return app


if __name__ == "__main__":
    uvicorn.run(application(), host="0.0.0.0", port=8000, access_log=False)
