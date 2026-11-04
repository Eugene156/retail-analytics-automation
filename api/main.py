"""Authenticated, bounded calculation adapter over fixed PostgreSQL functions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import DecimalException
import json
import os
from pathlib import Path
import re
import secrets
import threading
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator, model_validator
from api.preview import CSP, render_preview
from api.reviewer import ReviewerGuard, ReviewerStore
from api.portal import PortalStore, install_portal
from api.observability import SafeRequestLogging

SOURCE_HASH = "BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980"
LONDON = ZoneInfo("Europe/London")
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
QUERY = "SELECT retail.api_comparison_report_v1(%s, %s, %s, %s)"


def unambiguous_source_time(value: datetime) -> datetime:
    # Reject unrelated years before timezone/shift arithmetic can overflow.
    if not 2009 <= value.year <= 2011:
        raise ValueError("Timestamp is outside the pinned historical years")
    local = value.astimezone(LONDON).replace(tzinfo=None)
    validate_local(local)
    return local


def validate_local(local: datetime) -> timedelta:
    offsets = set()
    for fold in (0, 1):
        candidate = local.replace(tzinfo=LONDON, fold=fold)
        returned = candidate.astimezone(timezone.utc).astimezone(LONDON).replace(tzinfo=None)
        if returned == local:
            offsets.add(candidate.utcoffset())
    if len(offsets) != 1:
        raise ValueError("Ambiguous or nonexistent source-time boundary")
    return offsets.pop()


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file_sha256: Literal[SOURCE_HASH]
    source_time_interpretation: Literal["Europe/London-assumed"]
    period_start_inclusive: AwareDatetime
    period_end_exclusive: AwareDatetime
    source_as_of_exclusive: AwareDatetime

    @field_validator("period_start_inclusive", "period_end_exclusive", "source_as_of_exclusive", mode="before")
    @classmethod
    def explicit_timestamp(cls, value):
        if not isinstance(value, str) or not RFC3339.fullmatch(value):
            raise ValueError("An RFC3339 timestamp with explicit offset is required")
        return value

    @model_validator(mode="after")
    def bounded_period(self):
        start, end, cutoff = self.source_arguments()
        if not start < end <= cutoff or end - start > timedelta(days=31):
            raise ValueError("Invalid bounded period or source cutoff")
        for left, right in ((start, end), (start - timedelta(days=7), end - timedelta(days=7))):
            validate_local(left)
            validate_local(right)
            if validate_local(left) != validate_local(right - timedelta(microseconds=1)):
                raise ValueError("Source periods crossing a DST transition are unsupported")
        return self

    def source_arguments(self):
        return tuple(unambiguous_source_time(value) for value in (
            self.period_start_inclusive, self.period_end_exclusive, self.source_as_of_exclusive))


class ProposalRequest(BaseModel):
    """Service preparation only; no caller-provided reviewer, target or TTL."""
    model_config = ConfigDict(extra="forbid")
    report_revision: Literal[1]
    report_payload_sha256: str

    @field_validator("report_revision", mode="before")
    @classmethod
    def exact_revision(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Only integer report revision 1 is supported")
        return value

    @field_validator("report_payload_sha256", mode="before")
    @classmethod
    def exact_hash(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("One lowercase report SHA-256 is required")
        return value


class ApprovalRequestV2(ProposalRequest):
    """Explicit first/expired-successor issuance; no implicit renewal."""
    predecessor_proposal_id: UUID | None

    @field_validator("predecessor_proposal_id", mode="before")
    @classmethod
    def canonical_predecessor(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
            raise ValueError("Canonical nonzero predecessor UUID required")
        return value


@dataclass(repr=False)
class Settings:
    token: str
    dsn: str
    case_dsn: str | None = None
    reviewer_dsn: str | None = None
    portal_dsn: str | None = None
    portal_login_key: str | None = None

    @classmethod
    def from_environment(cls):
        try:
            token = Path(os.environ["RAA_API_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
            dsn = Path(os.environ["RAA_DATABASE_DSN_FILE"]).read_text(encoding="utf-8").strip()
            case_path = Path(os.environ["RAA_DATABASE_DSN_FILE"]).parent / "case-dsn"
            case_dsn = case_path.read_text(encoding="utf-8").strip()
            reviewer_path = case_path.parent / "reviewer-dsn"
            reviewer_dsn = reviewer_path.read_text(encoding="utf-8").strip() if reviewer_path.is_file() else None
            portal_path, key_path = case_path.parent / "portal-dsn", case_path.parent / "portal-login-key"
            if portal_path.is_file() != key_path.is_file():
                raise ValueError("Partial portal configuration")
            portal_dsn = portal_path.read_text(encoding="utf-8").strip() if portal_path.is_file() else None
            portal_key = key_path.read_text(encoding="utf-8").strip() if key_path.is_file() else None
            if portal_key is not None and (not portal_dsn or not re.fullmatch(r"[a-f0-9]{64}", portal_key)):
                raise ValueError("Invalid portal configuration")
            if not re.fullmatch(r"[a-f0-9]{64}", token) or not dsn or not case_dsn:
                raise ValueError("Invalid configuration")
        except (KeyError, OSError, ValueError):
            raise RuntimeError("Calculation API secret configuration is unavailable") from None
        return cls(token, dsn, case_dsn, reviewer_dsn, portal_dsn, portal_key)


class GuardMiddleware:
    """Authenticate before body parsing; bound actual bytes, including chunked bodies."""
    def __init__(self, app, token):
        self.app = app
        self.expected = ("Bearer " + token).encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        protected = scope["path"].startswith("/api/") or scope["path"] in ("/readyz", "/openapi.json")
        if protected:
            values = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
            if len(values) != 1 or not secrets.compare_digest(values[0], self.expected):
                return await JSONResponse({"detail": "Unauthorized"}, status_code=401,
                    headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        if protected and scope["method"] == "POST":
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > 8192:
                    return await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


class Calculator:
    def __init__(self, settings):
        self.settings = settings
        self.slot = threading.BoundedSemaphore(1)

    def connect(self):
        conn = psycopg.connect(self.settings.dsn, connect_timeout=5,
                               options="-c statement_timeout=120000 -c default_transaction_read_only=on")
        conn.read_only = True
        return conn

    @staticmethod
    def check_identity(conn):
        identity = conn.execute("SELECT current_user, current_database()").fetchone()
        if identity != ("raa_wp2_api", "raa_wp2_validation"):
            raise HTTPException(503, "Calculation database configuration is unavailable")

    def ready(self):
        try:
            with self.connect() as conn:
                self.check_identity(conn)
                installed = conn.execute("SELECT has_function_privilege(current_user, "
                    "'retail.api_comparison_report_v1(text,timestamp,timestamp,timestamp)', 'EXECUTE')").fetchone()
                if installed != (True,):
                    raise HTTPException(503, "Calculation database is not ready")
        except psycopg.Error:
            raise HTTPException(503, "Calculation database is not ready") from None

    def calculate(self, payload):
        if not self.slot.acquire(blocking=False):
            raise HTTPException(429, "Calculation is busy", headers={"Retry-After": "5"})
        try:
            with self.connect() as conn:
                self.check_identity(conn)
                row = conn.execute(QUERY, (payload.source_file_sha256, *payload.source_arguments())).fetchone()
                if row is None or not isinstance(row[0], str):
                    raise HTTPException(503, "Calculation result is unavailable")
                return row[0]
        except psycopg.errors.InvalidParameterValue:
            raise HTTPException(422, "Period or cutoff is outside the supported source span") from None
        except psycopg.errors.QueryCanceled:
            raise HTTPException(504, "Calculation exceeded its time limit") from None
        except psycopg.errors.RaiseException:
            raise HTTPException(409, "Source validation failed") from None
        except psycopg.Error:
            raise HTTPException(503, "Calculation database is unavailable") from None
        finally:
            self.slot.release()


class CaseStore:
    """Separate scoped write login; every query is a fixed definer function."""
    def __init__(self, settings, slot):
        self.settings = settings
        self.slot = slot
        self.approval_slot = threading.BoundedSemaphore(1)

    def query(self, sql, arguments, read_only=False):
        if not self.settings.case_dsn:
            raise HTTPException(503, "Report persistence is unavailable")
        try:
            with psycopg.connect(self.settings.case_dsn, connect_timeout=5,
                    options="-c statement_timeout=120000 -c lock_timeout=5000 -c timezone=UTC") as conn:
                conn.read_only = read_only
                if conn.execute("SELECT current_user, current_database()").fetchone() != (
                        "raa_wp2_case_api", "raa_wp2_validation"):
                    raise HTTPException(503, "Report database configuration is unavailable")
                value = conn.execute(sql, arguments).fetchone()[0]
            # The transaction has committed before any successful result escapes.
            return value
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "Idempotency key already binds a different request") from None
        except psycopg.errors.InvalidParameterValue:
            raise HTTPException(422, "Period or cutoff is outside the supported source span") from None
        except psycopg.errors.LockNotAvailable:
            raise HTTPException(429, "Report is busy", headers={"Retry-After": "5"}) from None
        except psycopg.errors.QueryCanceled:
            raise HTTPException(504, "Report calculation exceeded its time limit") from None
        except psycopg.errors.RaiseException:
            raise HTTPException(409, "Source or report request validation failed") from None
        except psycopg.errors.ObjectNotInPrerequisiteState:
            raise HTTPException(503, "Reviewer policy is unavailable") from None
        except psycopg.Error:
            raise HTTPException(503, "Report database is unavailable") from None

    def ready(self):
        # Fixed read function with a nonexistent identifier; no business mutation.
        self.query("SELECT retail.api_get_case_v1(%s)", (UUID(int=0),), read_only=True)

    def proposal(self, case_id):
        value = self.query("SELECT retail.api_get_approval_proposal_v1(%s)", (case_id,), read_only=True)
        if value is None:
            raise HTTPException(404, "Approval proposal not found")
        return value

    def issue_approval_request(self, case_id, key, payload):
        # One existing worker; reject bursts before opening scoped DB logins.
        # Cross-process correctness still comes from case locks/constraints.
        if not self.approval_slot.acquire(blocking=False):
            raise HTTPException(429, "Approval request is busy", headers={"Retry-After": "5"})
        try:
            value = self.query("SELECT retail.api_issue_approval_request_v2(%s, %s, %s, %s, %s)",
                (case_id, payload.report_revision, payload.report_payload_sha256, key, payload.predecessor_proposal_id))
        finally:
            self.approval_slot.release()
        if value is None:
            raise HTTPException(404, "Case not found")
        return value

    def approval_request(self, case_id, proposal_id=None):
        if proposal_id is None:
            value = self.query("SELECT retail.api_current_approval_request_v2(%s)", (case_id,), read_only=True)
        else:
            value = self.query("SELECT retail.api_get_approval_request_v2(%s, %s)", (case_id, proposal_id), read_only=True)
        if value is None:
            raise HTTPException(404, "Approval request not found")
        return value

    def get(self, case_id):
        value = self.query("SELECT retail.api_get_case_v1(%s)", (case_id,), read_only=True)
        if value is None:
            raise HTTPException(404, "Case not found")
        return value

    def submit(self, key, payload):
        value = self.query("SELECT retail.api_reserve_report_v1(%s, %s, %s, %s, %s)",
                           (key, payload.source_file_sha256, *payload.source_arguments()))
        saved = json.loads(value)
        if saved["state"] in ("awaiting_approval", "approved", "rejected"):
            return value, 200
        # Reservation is durable even if admission fails, SQL fails or we crash.
        if not self.slot.acquire(blocking=False):
            return value, 202
        try:
            try:
                result = self.query("SELECT retail.api_finish_report_v1(%s)", (UUID(saved["case_id"]),))
                if result is None:
                    raise HTTPException(503, "Report result is unavailable")
                return result, 200
            except HTTPException as error:
                if error.status_code == 429:
                    return value, 202
                error.headers = {**(error.headers or {}), "Location": "/api/v1/cases/" + saved["case_id"]}
                raise
        finally:
            self.slot.release()

    def revision(self, case_id, revision):
        if revision != 1:
            raise HTTPException(404, "Draft revision not found")
        value = self.query("SELECT retail.api_get_revision_v1(%s, %s)", (case_id, revision), read_only=True)
        if value is None:
            raise HTTPException(404, "Draft revision not found")
        return value


def create_app(settings, calculator=None, case_store=None, reviewer_store=None, portal_store=None):
    calculator = calculator or Calculator(settings)
    case_store = case_store or CaseStore(settings, getattr(calculator, "slot", threading.BoundedSemaphore(1)))
    app = FastAPI(title="Retail Analytics bounded calculation API", version="0.1.0-wp2",
                  openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(GuardMiddleware, token=settings.token)
    reviewer_store = reviewer_store or ReviewerStore(settings.reviewer_dsn)
    app.add_middleware(ReviewerGuard, store=reviewer_store)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Never echo hostile inputs, tokens, SQL details or connection strings.
        return JSONResponse({"detail": "Invalid calculation request"}, status_code=422)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        calculator.ready()
        if settings.case_dsn:
            case_store.ready()
        return {"status": "ready"}

    @app.post("/api/v1/calculations/comparison", response_class=Response,
              responses={200: {"content": {"application/json": {"schema": {"type": "object"}}}}})
    def calculate(payload: CalculationRequest):
        # Preserve PostgreSQL's NUMERIC JSON text without a binary-float round trip.
        return Response(content=calculator.calculate(payload), media_type="application/json",
                        headers={"Cache-Control": "no-store",
                                 "X-Source-Time-Interpretation": "Europe/London-assumed"})

    @app.post("/api/v1/report-requests", response_class=Response,
              responses={200: {"description": "Immutable draft is stored"},
                         202: {"description": "Request stored; repeat the same request/key to resume"},
                         409: {"description": "Key conflict or source validation failure"}},
              openapi_extra={"parameters": [{"name": "Idempotency-Key", "in": "header", "required": True,
                  "schema": {"type": "string", "pattern": "^[A-Za-z0-9_-]{8,128}$"}}]})
    def report_request(payload: CalculationRequest, request: Request):
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", keys[0]):
            raise HTTPException(422, "One valid Idempotency-Key header is required")
        value, status = case_store.submit(keys[0], payload)
        metadata = json.loads(value)
        headers = {"Cache-Control": "no-store", "Location": "/api/v1/cases/" + metadata["case_id"]}
        if status == 202:
            headers["Retry-After"] = "5"
        return Response(value, status_code=status, media_type="application/json", headers=headers)

    @app.get("/api/v1/cases/{case_id}", response_class=Response)
    def get_case(case_id: UUID):
        return Response(case_store.get(case_id), media_type="application/json", headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/cases/{case_id}/revisions/{revision}", response_class=Response)
    def get_draft_revision(case_id: UUID, revision: int):
        return Response(case_store.revision(case_id, revision), media_type="application/json",
                        headers={"Cache-Control": "no-store", "X-Report-Status": report_status(case_store.get(case_id)),
                                 "X-Source-Time-Interpretation": "Europe/London-assumed"})

    @app.get("/api/v1/cases/{case_id}/revisions/{revision}/preview", response_class=Response,
             responses={200: {"content": {"text/html": {}}}, 409: {"description": "Draft validation failed"}})
    def draft_preview(case_id: UUID, revision: int):
        # Only fixed read functions; do not reserve, calculate or record a decision.
        if revision != 1:
            raise HTTPException(404, "Draft revision not found")
        metadata = case_store.get(case_id)
        payload = case_store.revision(case_id, revision)
        try:
            html = render_preview(metadata, payload, case_id, revision)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError, DecimalException):
            raise HTTPException(409, "Stored draft preview validation failed") from None
        return Response(html, media_type="text/html", headers={"Cache-Control": "no-store",
            "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Report-Status": report_status(metadata)})

    @app.post("/api/v1/cases/{case_id}/approval-proposal", response_class=Response,
              deprecated=True, responses={410: {"description": "Use explicit v2 request identity/predecessor"}})
    def prepare_proposal(case_id: UUID):
        raise HTTPException(410, "Legacy preparation retired; use explicit v2 approval requests",
                            headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.get("/api/v1/cases/{case_id}/approval-proposal", response_class=Response)
    def get_proposal(case_id: UUID):
        return Response(case_store.proposal(case_id), media_type="application/json",
            headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.post("/api/v2/cases/{case_id}/approval-requests", response_class=Response,
              responses={200: {"description": "Immutable request created/replayed; decisions disabled"},
                         409: {"description": "Changed key binding, active/wrong predecessor or report conflict"}},
              openapi_extra={"parameters": [{"name": "Idempotency-Key", "in": "header", "required": True,
                  "schema": {"type": "string", "pattern": "^[A-Za-z0-9_-]{8,128}$"}}]})
    def issue_request(case_id: UUID, payload: ApprovalRequestV2, request: Request):
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", keys[0]):
            raise HTTPException(422, "One valid Idempotency-Key header is required")
        value = case_store.issue_approval_request(case_id, keys[0], payload)
        proposal_id = json.loads(value)["proposal"]["proposal_id"]
        return Response(value, media_type="application/json", headers={"Cache-Control": "no-store",
            "X-Decision-Enabled": "false", "Location": f"/api/v2/cases/{case_id}/approval-requests/{proposal_id}"})

    @app.get("/api/v2/cases/{case_id}/approval-requests/current", response_class=Response)
    def current_request(case_id: UUID):
        return Response(case_store.approval_request(case_id), media_type="application/json",
                        headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.get("/api/v2/cases/{case_id}/approval-requests/{proposal_id}", response_class=Response)
    def get_request(case_id: UUID, proposal_id: UUID):
        return Response(case_store.approval_request(case_id, proposal_id), media_type="application/json",
                        headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.get("/openapi.json", include_in_schema=False)
    def openapi():
        schema = app.openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["CalculationToken"] = {
            "type": "http", "scheme": "bearer"}
        schema["components"]["securitySchemes"]["OwnerReadToken"] = {"type": "http", "scheme": "bearer"}
        for path, methods in schema["paths"].items():
            if path != "/healthz":
                for operation in methods.values():
                    operation["security"] = [{"OwnerReadToken" if path.startswith("/review/") else "CalculationToken": []}]
        return schema

    @app.get("/review/v1/identity")
    def reviewer_identity(request: Request):
        return JSONResponse({"reviewer_id": str(request.state.reviewer_id), "access": "read-only",
            "approval_ttl_seconds": 86400, "decision_enabled": False, "published": False},
            headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.get("/review/v1/cases/{case_id}", response_class=Response)
    def reviewer_case(case_id: UUID, request: Request):
        return Response(reviewer_store.get(request.state.reviewer_digest, case_id), media_type="application/json",
                        headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.get("/review/v1/cases/{case_id}/approval-proposal", response_class=Response)
    def reviewer_proposal(case_id: UUID, request: Request):
        return Response(reviewer_store.proposal(request.state.reviewer_digest, case_id), media_type="application/json",
                        headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.get("/review/v2/cases/{case_id}/approval-requests/current", response_class=Response)
    def reviewer_current_request(case_id: UUID, request: Request):
        return Response(reviewer_store.approval_request(request.state.reviewer_digest, case_id),
            media_type="application/json", headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.get("/review/v2/cases/{case_id}/approval-requests/{proposal_id}", response_class=Response)
    def reviewer_get_request(case_id: UUID, proposal_id: UUID, request: Request):
        return Response(reviewer_store.approval_request(request.state.reviewer_digest, case_id, proposal_id),
            media_type="application/json", headers={"Cache-Control": "no-store", "X-Decision-Enabled": "false"})

    @app.get("/review/v1/cases/{case_id}/revisions/{revision}/preview", response_class=Response)
    def reviewer_preview(case_id: UUID, revision: int, request: Request):
        digest = request.state.reviewer_digest
        payload = reviewer_store.revision(digest, case_id, revision)
        metadata = reviewer_store.get(digest, case_id)
        try:
            html = render_preview(metadata, payload, case_id, revision)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError, DecimalException):
            raise HTTPException(409, "Stored draft preview validation failed") from None
        return Response(html, media_type="text/html", headers={"Cache-Control": "no-store",
            "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "X-Report-Status": report_status(metadata), "X-Decision-Enabled": "false"})

    install_portal(app, portal_store or PortalStore(settings.portal_dsn, decisions_enabled=True), settings.portal_login_key)
    from api.overview import OverviewMiddleware
    app.add_middleware(OverviewMiddleware)
    app.add_middleware(SafeRequestLogging, service='retail-api')
    return app


def report_status(metadata):
    state = json.loads(metadata)["state"]
    if state not in ("awaiting_approval", "approved", "rejected"):
        raise HTTPException(409, "Stored report state is invalid")
    return "unapproved-draft" if state == "awaiting_approval" else state+"-unpublished"


def application():
    """Uvicorn factory: secret loading only at runtime, not module import."""
    return create_app(Settings.from_environment())
