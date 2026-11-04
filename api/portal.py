"""Fixed-origin owner review portal; publication remains disabled."""
from dataclasses import dataclass
from decimal import DecimalException
from hashlib import sha256
from html import escape
import hmac
import json
import re
import secrets
import threading
import time
from urllib.parse import parse_qsl
from uuid import UUID

import psycopg
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from api.preview import render_preview, CSP as PREVIEW_CSP

ORIGIN = "http://127.0.0.1:18081"
SESSION = "raa_portal_session"
CHALLENGE = "raa_portal_login"


@dataclass(frozen=True)
class PortalBoundary:
    """Closed trusted profiles, never a caller-selected URL/cookie namespace."""
    profile: str = 'legacy'

    def __post_init__(self):
        if self.profile not in ('legacy', 'isolated-uat'):
            raise ValueError('Fixed portal boundary required')

    @property
    def origin(self):
        return ORIGIN if self.profile == 'legacy' else 'http://127.0.0.1:18082'

    @property
    def host(self):
        return self.origin.removeprefix('http://')

    @property
    def session(self):
        return SESSION if self.profile == 'legacy' else 'raa_portal_uat_session'

    @property
    def challenge(self):
        return CHALLENGE if self.profile == 'legacy' else 'raa_portal_uat_login'


LEGACY_BOUNDARY = PortalBoundary()
UAT_BOUNDARY = PortalBoundary('isolated-uat')
HEX = re.compile(r"[a-f0-9]{64}\Z")
CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
HEADERS = {"Cache-Control": "no-store", "Content-Security-Policy": CSP,
           # Native same-origin form POSTs need a non-null Origin. Suppress
           # cross-origin referrers without relaxing the strict Origin guard.
           "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff",
           "X-Decision-Enabled": "false"}


def digest(value):
    return sha256(value.encode("ascii")).hexdigest()


def session_csrf(value):
    return hmac.new(bytes.fromhex(value), b"raa-portal-csrf-v1", "sha256").hexdigest()


class PortalStore:
    def __init__(self, dsn, decisions_enabled=False):
        self.dsn, self.slot = dsn, threading.BoundedSemaphore(1)
        self.decisions_enabled = decisions_enabled

    def query(self, sql, arguments, write=False):
        if not self.dsn:
            raise HTTPException(503, "Portal access is unavailable")
        if not self.slot.acquire(blocking=False):
            raise HTTPException(429, "Portal is busy", headers={"Retry-After": "5"})
        try:
            with psycopg.connect(self.dsn, connect_timeout=5, options=
                    "-c statement_timeout=5000 -c lock_timeout=5000 -c timezone=UTC") as conn:
                conn.read_only = not write
                if conn.execute("SELECT current_user,current_database()").fetchone() != (
                        "raa_wp4_portal_api", "raa_wp2_validation"):
                    raise HTTPException(503, "Portal access is unavailable")
                return conn.execute(sql, arguments).fetchone()[0]
        except psycopg.errors.InsufficientPrivilege:
            raise HTTPException(401, "Unauthorized") from None
        except (psycopg.errors.LockNotAvailable, psycopg.errors.ProgramLimitExceeded):
            raise HTTPException(429, "Portal is busy", headers={"Retry-After": "5"}) from None
        except (psycopg.errors.ObjectNotInPrerequisiteState, psycopg.errors.UniqueViolation):
            raise HTTPException(409, "Decision conflicts with current request or prior decision") from None
        except psycopg.errors.InvalidParameterValue:
            raise HTTPException(422, "Invalid decision binding") from None
        except psycopg.Error:
            raise HTTPException(503, "Portal access is unavailable") from None
        finally:
            self.slot.release()

    def identity(self, session):
        value = self.query("SELECT retail.api_portal_identity_v1(%s)", (session,))
        if value is None:
            raise HTTPException(401, "Unauthorized")
        return UUID(str(value))

    def login(self, owner, session, csrf, old):
        return self.query("SELECT retail.api_portal_login_v1(%s,%s,%s,%s)", (owner, session, csrf, old), True)

    def logout(self, session, csrf):
        return self.query("SELECT retail.api_portal_logout_v1(%s,%s)", (session, csrf), True)

    def required(self, sql, arguments):
        value = self.query(sql, arguments)
        if value is None:
            raise HTTPException(404, "Review object not found")
        return value

    def requests(self, session):
        return self.required("SELECT retail.api_portal_requests_v1(%s)", (session,))

    def proposal(self, session, case, proposal):
        return self.required("SELECT retail.api_portal_request_v1(%s,%s,%s)", (session, case, proposal))

    def case(self, session, case):
        return self.required("SELECT retail.api_portal_case_v1(%s,%s)", (session, case))

    def revision(self, session, case):
        return self.required("SELECT retail.api_portal_revision_v1(%s,%s,1)", (session, case))

    def decide(self, session, csrf, case, proposal, form):
        if not self.decisions_enabled:
            raise HTTPException(405, "Decisions are disabled")
        value = self.query("SELECT retail.api_decide_request_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (session, csrf, case, proposal, 1, form["report_sha256"], form["proposal_sha256"],
             form["choice"], form["decision_key"]), True)
        if value is None:
            raise HTTPException(404, "Review object not found")
        return value


def cookies(headers, session_cookie=SESSION):
    values = [v for k, v in headers if k.lower() == b"cookie"]
    if len(values) > 1:
        raise HTTPException(400, "Invalid portal request")
    result = {}
    if values:
        for part in values[0].decode("ascii").split(";"):
            name, separator, value = part.strip().partition("=")
            if not separator or not name or name in result:
                raise HTTPException(400, "Invalid portal request")
            result[name] = value
    if session_cookie in result and not HEX.fullmatch(result[session_cookie]):
        raise HTTPException(401, "Unauthorized")
    return result


class PortalGuard:
    def __init__(self, app, store, key, boundary=LEGACY_BOUNDARY, demo_document_navigation=False):
        if type(boundary) is not PortalBoundary:
            raise ValueError('Fixed portal boundary required')
        self.app, self.store, self.key = app, store, key
        self.boundary = boundary
        if demo_document_navigation and boundary != UAT_BOUNDARY:
            raise ValueError('Demo navigation requires the isolated boundary')
        self.demo_document_navigation = demo_document_navigation

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"] == "/portal" or scope["path"].startswith("/portal/")):
            return await self.app(scope, receive, send)
        original_send = send

        async def private_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers.extend((k.lower().encode(), v.encode()) for k, v in HEADERS.items()
                               if k.lower().encode() not in present)
                message = {**message, "headers": headers}
            await original_send(message)

        send = private_send
        try:
            if not self.key:
                raise HTTPException(503, "Portal access is unavailable")
            def values(name):
                return [v for k, v in scope["headers"] if k.lower() == name]
            query = scope.get("query_string", b"")
            tracking_login = (self.demo_document_navigation and scope["method"] == "GET"
                and scope["path"] == "/portal/login" and query == b"utm_source=chatgpt.com")
            tracking_index = (self.demo_document_navigation and scope["method"] == "GET"
                and scope["path"] == "/portal" and query == b"utm_source=chatgpt.com")
            if values(b"host") != [self.boundary.host.encode()] or (query and not (tracking_login or tracking_index)) or values(b"authorization"):
                raise HTTPException(400, "Invalid portal request")
            origins = values(b"origin")
            if (origins and origins != [self.boundary.origin.encode()]) or (scope["method"] == "POST" and not origins):
                raise HTTPException(403, "Invalid portal origin")
            document_navigation = (self.demo_document_navigation and scope["method"] == "GET"
                and not origins and values(b"sec-fetch-mode") == [b"navigate"]
                and values(b"sec-fetch-dest") == [b"document"]
                and values(b"sec-fetch-site") in ([b"same-site"], [b"cross-site"]))
            if values(b"sec-fetch-site") and values(b"sec-fetch-site") not in ([b"same-origin"], [b"none"]) and not document_navigation:
                raise HTTPException(403, "Invalid portal origin")
            saved_cookies = cookies(scope["headers"], self.boundary.session)
            scope.setdefault("state", {})["portal_cookies"] = saved_cookies
            if scope["method"] not in ("GET", "POST"):
                raise HTTPException(405, "Method not allowed")
            if tracking_login:
                return await RedirectResponse("/portal/login", 303, headers=HEADERS)(scope, receive, send)
            if scope["path"] != "/portal/login":
                raw = saved_cookies.get(self.boundary.session)
                if not raw:
                    raise HTTPException(401, "Unauthorized")
                identity = await run_in_threadpool(self.store.identity, digest(raw))
                scope["state"].update(portal_digest=digest(raw), portal_identity=identity, portal_csrf=session_csrf(raw))
            if tracking_index:
                return await RedirectResponse("/portal", 303, headers=HEADERS)(scope, receive, send)
            if scope["method"] == "POST":
                decision_path = bool(re.fullmatch(r"/portal/cases/[a-f0-9-]{36}/requests/[a-f0-9-]{36}/decision", scope["path"]))
                if scope["path"] not in ("/portal/login", "/portal/logout") and not (
                        decision_path and getattr(self.store, "decisions_enabled", False)):
                    raise HTTPException(405, "Portal is read-only")
                if values(b"content-type") != [b"application/x-www-form-urlencoded"]:
                    raise HTTPException(415, "Encoded form required")
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] != "http.request":
                        raise HTTPException(400, "Invalid portal request")
                    body.extend(message.get("body", b""))
                    if len(body)>2048:
                        raise HTTPException(413, "Form is too large")
                    if not message.get("more_body", False):
                        break
                if re.search(rb"%(?![a-fA-F0-9]{2})", body):
                    raise HTTPException(400, "Invalid portal form")
                fields = parse_qsl(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True,
                                   encoding="utf-8", errors="strict", max_num_fields=7)
                form = dict(fields)
                expected = ({"owner_token", "csrf"} if scope["path"] == "/portal/login" else
                    {"csrf", "revision", "report_sha256", "proposal_sha256", "choice", "decision_key", "confirm"}
                    if decision_path else {"csrf"})
                if len(fields)!=len(form) or set(form)!=expected or not HEX.fullmatch(form["csrf"]):
                    raise HTTPException(400, "Invalid portal form")
                if decision_path:
                    if not hmac.compare_digest(scope["state"]["portal_csrf"], form["csrf"]):
                        raise HTTPException(403, "Invalid decision challenge")
                    if form["revision"] != "1" or not HEX.fullmatch(form["report_sha256"]) \
                            or not HEX.fullmatch(form["proposal_sha256"]) or form["choice"] not in ("approve", "reject", "expire") \
                            or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", form["decision_key"]) or form["confirm"] != "yes":
                        raise HTTPException(422, "Exact confirmed decision required")
                scope["state"]["portal_form"] = form
            return await self.app(scope, receive, send)
        except (ValueError, UnicodeError):
            error = HTTPException(400, "Invalid portal request")
        except HTTPException as caught:
            error = caught
        if error.status_code == 401 and scope["method"] == "GET" and scope["path"] != "/portal/login":
            response = RedirectResponse("/portal/login", 303)
            response.delete_cookie(self.boundary.session, path="/portal", httponly=True, samesite="strict")
        else:
            response = JSONResponse({"detail": error.detail}, error.status_code, headers=error.headers)
        return await response(scope, receive, send)


def page(title, content, csrf=None, decisions_enabled=False):
    logout = "" if csrf is None else ('<form action="/portal/logout" method="post">'
        f'<input type="hidden" name="csrf" value="{escape(csrf)}"><button>Sign out</button></form>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title><style>body{{font:17px system-ui;margin:2rem auto;max-width:900px;'
        'padding:0 1rem;background:#f5f7fa;color:#18283b}main{background:white;padding:1.5rem;border-radius:12px}'
        'input,button{font:inherit;padding:.6rem;margin:.5rem 0;max-width:100%;box-sizing:border-box}'
        'input[type=password]{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}'
        'li{margin:1rem 0}a{color:#1748a6}</style><main>'
        f'<h1>{escape(title)}</h1><p>Local validation · '
        f'{"owner decisions enabled · publication disabled" if decisions_enabled else "read-only · decisions disabled"}'
        f'</p>{content}{logout}</main></html>')


def html(content):
    return Response(content, media_type="text/html", headers=HEADERS)


def _install_auth_routes(app, store, key, portal_html, boundary=LEGACY_BOUNDARY):
    """Shared native auth forms; installer supplies scoped store and renderer."""
    if type(boundary) is not PortalBoundary:
        raise ValueError('Fixed portal boundary required')
    @app.get("/portal/login", include_in_schema=False)
    def login_page():
        nonce, issued = secrets.token_hex(32), str(int(time.time()))
        unsigned = nonce + "." + issued
        signed = unsigned + "." + hmac.new(bytes.fromhex(key), unsigned.encode(), "sha256").hexdigest()
        response = portal_html("Owner sign-in", '<p>Use your separate local owner credential. '
            'Do not use the n8n service token. Session lifetime: one hour; approval requests: 24 hours.</p>'
            '<form action="/portal/login" method="post">'
            '<label for="token">Owner token</label><input id="token" name="owner_token" type="password" '
            'required minlength="64" maxlength="64" autocomplete="off">'
            f'<input type="hidden" name="csrf" value="{nonce}"><button>Sign in</button></form>'
            '<p>This HTTP loopback portal is for a trusted local browser only. Publishing is unavailable.</p>')
        response.set_cookie(boundary.challenge, signed, max_age=300, path="/portal/login", httponly=True, samesite="strict")
        return response

    @app.post("/portal/login", include_in_schema=False)
    def login(request: Request):
        form = request.state.portal_form
        challenge = request.state.portal_cookies.get(boundary.challenge, "")
        if not re.fullmatch(r"[a-f0-9]{64}\.[0-9]{10}\.[a-f0-9]{64}", challenge):
            raise HTTPException(403, "Invalid login challenge")
        nonce, issued, signature = challenge.split(".")
        expected = hmac.new(bytes.fromhex(key), (nonce+"."+issued).encode(), "sha256").hexdigest()
        if not hmac.compare_digest(signature, expected) or not hmac.compare_digest(nonce, form["csrf"]) \
                or not 0<=time.time()-int(issued)<300:
            raise HTTPException(403, "Invalid login challenge")
        if not HEX.fullmatch(form["owner_token"]):
            raise HTTPException(401, "Unauthorized")
        raw = secrets.token_hex(32)
        old = request.state.portal_cookies.get(boundary.session)
        store.login(digest(form["owner_token"]), digest(raw), digest(session_csrf(raw)), digest(old) if old else None)
        response = RedirectResponse("/portal", 303, headers=HEADERS)
        response.set_cookie(boundary.session, raw, max_age=3600, path="/portal", httponly=True, samesite="strict")
        response.delete_cookie(boundary.challenge, path="/portal/login", httponly=True, samesite="strict")
        return response

    @app.post("/portal/logout", include_in_schema=False)
    def logout(request: Request):
        if not hmac.compare_digest(request.state.portal_csrf, request.state.portal_form["csrf"]):
            raise HTTPException(403, "Invalid logout challenge")
        store.logout(request.state.portal_digest, digest(request.state.portal_form["csrf"]))
        response = RedirectResponse("/portal/login", 303, headers=HEADERS)
        response.delete_cookie(boundary.session, path="/portal", httponly=True, samesite="strict")
        return response


def install_portal(app, store, key):
    app.add_middleware(PortalGuard, store=store, key=key)
    enabled = getattr(store, "decisions_enabled", False)

    def portal_html(title, content, csrf=None):
        response = html(page(title, content, csrf, enabled))
        response.headers["X-Decision-Enabled"] = str(enabled).lower()
        return response

    _install_auth_routes(app, store, key, portal_html)

    @app.get("/portal", include_in_schema=False)
    def requests(request: Request):
        try:
            rows = json.loads(store.requests(request.state.portal_digest))
            if not isinstance(rows, list) or len(rows)>20:
                raise ValueError()
            links = []
            for row in rows:
                case, proposal = UUID(row["case_id"]), UUID(row["proposal_id"])
                status = row["review_status"]
                if status not in ("pending_review", "expired", "approved", "rejected"):
                    raise ValueError()
                links.append(f'<li><a href="/portal/cases/{case}/requests/{proposal}">Request {proposal}</a>'
                    f'<br>{escape(status)} · expires {escape(row["expires_at"])} · case {case}</li>')
            content = '<p>Latest request per case, up to 20. Viewing does not renew or approve a request.</p>'
            content += '<ul>'+"".join(links)+'</ul>' if links else '<p>No approval requests.</p>'
            return portal_html("Approval requests", content, request.state.portal_csrf)
        except (ValueError, TypeError, KeyError):
            raise HTTPException(409, "Stored request validation failed") from None

    @app.get("/portal/cases/{case_id}/requests/{proposal_id}", include_in_schema=False)
    def detail(case_id: UUID, proposal_id: UUID, request: Request):
        try:
            value = json.loads(store.proposal(request.state.portal_digest, case_id, proposal_id))
            canonical, proposal = value["canonical_payload_text"], value["proposal"]
            if sha256(canonical.encode("utf-8")).hexdigest() != value["proposal_sha256"] or json.loads(canonical) != proposal \
                    or UUID(proposal["case_id"]) != case_id or UUID(proposal["proposal_id"]) != proposal_id \
                    or UUID(proposal["reviewer_id"]) != request.state.portal_identity \
                    or not isinstance(value["decision_enabled"], bool) or value["published"] is not False \
                    or value["approved"] is not (value["review_status"] == "approved") \
                    or value["review_status"] not in ("pending_review", "expired", "superseded", "approved", "rejected"):
                raise ValueError()
            # Display exact canonical bytes escaped; never interpret descriptions or action URLs.
            content = f'<p><a href="/portal">All requests</a></p><p>Status: {escape(value["review_status"])}</p>'
            content += '<p>Unpublished. After expiry a new explicit request is required. Viewing never records a decision.</p>'
            content += f'<p><a href="/portal/cases/{case_id}/revisions/1/preview">View stored draft revision 1</a></p>'
            content += f'<p>Request SHA-256: {escape(value["proposal_sha256"])}</p><pre>{escape(canonical)}</pre>'
            receipt = value.get("review_receipt")
            if receipt is not None:
                validate_receipt(receipt, case_id, proposal_id, proposal["report_payload_sha256"],
                                 value["proposal_sha256"], request.state.portal_identity, value["review_status"])
                content += '<h2>Stored decision receipt</h2><pre>'+escape(receipt["canonical_payload_text"])+ '</pre>'
                content += '<p>Decision SHA-256: '+escape(receipt["decision_sha256"])+ '</p><p>Publication remains disabled.</p>'
            elif value["review_status"] in ("approved", "rejected"):
                raise ValueError()
            if enabled and value["decision_enabled"]:
                choice_buttons = ('<button name="choice" value="approve">Approve exact request</button> '
                    '<button name="choice" value="reject">Reject exact request</button>'
                    if value["review_status"] == "pending_review" else
                    '<button name="choice" value="expire">Record expiry (no approval)</button>')
                fields = {"csrf": request.state.portal_csrf, "revision": "1",
                    "report_sha256": proposal["report_payload_sha256"], "proposal_sha256": value["proposal_sha256"],
                    "decision_key": "review-"+secrets.token_hex(16)}
                content += f'<form action="/portal/cases/{case_id}/requests/{proposal_id}/decision" method="post">'
                content += ''.join(f'<input type="hidden" name="{name}" value="{escape(text)}">' for name,text in fields.items())
                content += '<label><input type="checkbox" name="confirm" value="yes" required> '
                content += 'I confirm my selected decision for this exact request, report hash and target.</label><br>'+choice_buttons+'</form>'
            return portal_html("Approval request", content, request.state.portal_csrf)
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise HTTPException(409, "Stored request validation failed") from None

    @app.post("/portal/cases/{case_id}/requests/{proposal_id}/decision", include_in_schema=False)
    def decide(case_id: UUID, proposal_id: UUID, request: Request):
        form = request.state.portal_form
        # Store returns only after the transaction's deferred constraints commit.
        result = store.decide(request.state.portal_digest, digest(form["csrf"]), case_id, proposal_id, form)
        try:
            validate_receipt(json.loads(result), case_id, proposal_id, form["report_sha256"], form["proposal_sha256"],
                request.state.portal_identity, {"approve":"approved", "reject":"rejected", "expire":"expired"}[form["choice"]])
        except (ValueError, TypeError, KeyError):
            raise HTTPException(503, "Decision result unavailable; inspect the request before retrying") from None
        return RedirectResponse(f"/portal/cases/{case_id}/requests/{proposal_id}", 303, headers=HEADERS)

    @app.get("/portal/cases/{case_id}/revisions/1/preview", include_in_schema=False)
    def preview(case_id: UUID, request: Request):
        session = request.state.portal_digest
        try:
            metadata = store.case(session, case_id)
            content = render_preview(metadata, store.revision(session, case_id), case_id, 1)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError, DecimalException):
            raise HTTPException(409, "Stored draft validation failed") from None
        return Response(content, media_type="text/html", headers={**HEADERS,
            "Content-Security-Policy": PREVIEW_CSP, "Referrer-Policy": "no-referrer",
            "X-Report-Status": "unapproved-draft" if json.loads(metadata)["state"] == "awaiting_approval"
                else json.loads(metadata)["state"]+"-unpublished"})


def validate_receipt(value, case, proposal, report_hash, proposal_hash, reviewer, outcome):
    canonical, decision = value["canonical_payload_text"], value["decision"]
    if sha256(canonical.encode("utf-8")).hexdigest() != value["decision_sha256"] or json.loads(canonical) != decision \
            or decision["case_id"] != str(case) or decision["proposal_id"] != str(proposal) \
            or decision["reviewer_id"] != str(reviewer) or decision["report_revision"] != 1 \
            or decision["report_payload_sha256"] != report_hash or decision["proposal_sha256"] != proposal_hash \
            or decision["outcome"] != outcome or value["published"] is not False or value["dispatch_enabled"] is not False:
        raise ValueError("Invalid stored decision receipt")
    if decision.get("contract_version") != "local-review-decision-v1" \
            or decision.get("canonicalization") != "postgresql-jsonb-text-v1" \
            or decision.get("proposal_contract_version") != "local-approval-proposal-v2":
        raise ValueError("Invalid decision contract")
    action = value["outbox"]
    if outcome == "approved":
        if not isinstance(action, dict) or action["state"] != "pending" or action["content_sha256"] != report_hash \
                or action["action_key"] != "publish-local-v1:"+str(proposal) \
                or action["target_id"] != "local-approved-report-json-v1" \
                or action["relative_path"] != "reports/approved/v1/"+str(case)+"/revision-1.json":
            raise ValueError("Invalid publication intent")
    elif action is not None:
        raise ValueError("Unexpected publication intent")
