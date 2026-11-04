"""Actual HTTP fail-closed proposal checks before owner identity is configured."""
import json
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from wp3_preview_local import BASE, ROOT, NoRedirect, fetch

CASE_ID = "61b10574-c842-4dae-8e8b-647f0d51ba55"


def main():
    if (ROOT / ".local" / "wp4-reviewer" / "credential.json").exists():
        raise ValueError("Pre-configuration check is no longer applicable; use wp4_reviewer_local.py check")
    token = (ROOT / ".local" / "wp2-api" / "token").read_text(encoding="utf-8").strip()
    opener = build_opener(ProxyHandler({}), NoRedirect())
    before = fetch(opener, token, CASE_ID, "application/json")
    original = fetch(opener, token, CASE_ID + "/revisions/1", "application/json")
    body = {"report_revision": 1, "report_payload_sha256": json.loads(before)["payload_sha256"]}

    def check(method, suffix, expected, payload=None, auth=token):
        headers = {"Content-Type": "application/json"}
        if auth is not None: headers["Authorization"] = "Bearer " + auth
        data = None if payload is None else json.dumps(payload).encode()
        try:
            with opener.open(Request(BASE + suffix, method=method, headers=headers, data=data), timeout=15) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
            error.close()
        if status != expected: raise ValueError("Unexpected proposal HTTP result")

    suffix = CASE_ID + "/approval-proposal"
    check("GET", suffix, 401, auth=None)
    check("POST", suffix, 401, body, auth="wrong")
    check("GET", suffix, 404)
    check("POST", suffix, 503, body)  # No reviewer configured: no live proposal.
    for field in ("reviewer_id", "target", "expires_at", "ttl_seconds", "approved"):
        check("POST", suffix, 422, {**body, field: "caller-value"})
    check("POST", suffix, 422, {**body, "report_revision": True})
    check("POST", CASE_ID + "/decision", 404, {"decision": "approve"})
    with opener.open(Request("http://127.0.0.1:18081/openapi.json", headers={"Authorization": "Bearer " + token}), timeout=15) as response:
        schema_bytes = response.read(524289)
    if len(schema_bytes) > 524288: raise ValueError("Oversized API schema")
    schema = json.loads(schema_bytes)
    operations = schema["paths"]["/api/v1/cases/{case_id}/approval-proposal"]
    if (any(operations[method]["security"] != [{"CalculationToken": []}] for method in ("get", "post"))
            or "/api/v1/cases/{case_id}/decision" in schema["paths"]):
        raise ValueError("Unexpected approval API surface")
    after = fetch(opener, token, CASE_ID, "application/json")
    if before != after or original != fetch(opener, token, CASE_ID + "/revisions/1", "application/json"):
        raise ValueError("Proposal guards mutated the draft")
    print("PASS|actual-http-proposal|auth-401|unconfigured-503|absent-404|caller-bindings-422|no-decision|protected-openapi|unchanged-case-and-bytes")


if __name__ == "__main__":
    try: main()
    except Exception:
        raise SystemExit("Live proposal check failed; private diagnostics suppressed") from None
