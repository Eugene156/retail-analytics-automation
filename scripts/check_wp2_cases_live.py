"""Actual HTTP persistence/replay checks, including project-container restarts.

Keeps one unapproved M02 case as evidence. Does not reset volumes or publish.
Secret values and exception details are never printed.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from check_wp2_api_live import CheckFailure, expect, payload

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18081"


def docker(arguments, stdin=None):
    result = subprocess.run(["docker", *arguments], input=stdin, text=True, capture_output=True, check=False)
    expect(result.returncode == 0, "docker-operation")
    return result.stdout.strip()


def http(token, method, path, value=None, key=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if key is not None:
        headers["Idempotency-Key"] = key
    request = Request(BASE + path, data=None if value is None else json.dumps(value).encode(),
                      method=method, headers=headers)
    try:
        response = urlopen(request, timeout=150)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), {k.lower(): v for k, v in response.headers.items()}


def restart_and_wait(token):
    # Explicitly named project containers; Docker retains both existing volumes.
    docker(["restart", "raa-g0-postgres-1"])
    docker(["restart", "raa-wp2-api"])
    for _ in range(30):
        try:
            if http(token, "GET", "/readyz")[0] == 200:
                return
        except (URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(0.5)
    raise CheckFailure("readiness-after-restart")


def main():
    token = (ROOT / ".local" / "wp2-api" / "token").read_text(encoding="utf-8").strip()
    key = "http-persist-" + uuid4().hex
    path = "/api/v1/report-requests"
    value = payload()
    expect(http(None, "POST", path, value, key)[0] == 401, "request-authentication")
    expect(http(token, "POST", path, value)[0] == 422, "missing-idempotency-key")
    expect(http(token, "POST", path, value, "bad/key")[0] == 422, "invalid-idempotency-key")
    # Duplicate headers are rejected, not silently combined or selected.
    connection = HTTPConnection("127.0.0.1", 18081, timeout=5)
    try:
        body = json.dumps(value).encode()
        connection.putrequest("POST", path)
        connection.putheader("Authorization", "Bearer " + token)
        connection.putheader("Idempotency-Key", key)
        connection.putheader("Idempotency-Key", key)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        expect(response.status == 422, "duplicate-idempotency-key")
        response.read()
    finally:
        connection.close()
    # Real scoped login: commit the reservation, cancel actual report SQL, close.
    # Child prints safe case metadata only; exception/secret output is suppressed.
    preparation = '''
import json
import psycopg
from api.main import Settings, SOURCE_HASH
try:
    dsn = Settings.from_environment().case_dsn
    with psycopg.connect(dsn) as conn:
        saved = conn.execute("SELECT retail.api_reserve_report_v1(%s,%s,%s,%s,%s)",
            (KEY, SOURCE_HASH, "2011-01-28 09:00", "2011-01-28 10:00", "2011-01-28 10:00")).fetchone()[0]
    cid = json.loads(saved)["case_id"]
    with psycopg.connect(dsn) as conn:
        conn.execute("SET LOCAL statement_timeout='50ms'")
        try:
            conn.execute("SELECT retail.api_finish_report_v1(%s)", (cid,))
            raise RuntimeError("Expected timeout")
        except psycopg.errors.QueryCanceled:
            conn.rollback()
        after = conn.execute("SELECT retail.api_get_case_v1(%s)", (cid,)).fetchone()[0]
        if json.loads(after) != json.loads(saved):
            raise RuntimeError("Changed pending case")
    print(after)
except Exception:
    raise SystemExit("FAIL|preparation|details-suppressed") from None
'''
    received = json.loads(docker(["exec", "-i", "raa-wp2-api", "python", "-"],
                                "KEY=" + repr(key) + "\n" + preparation))
    cid = str(UUID(received["case_id"]))
    case_path = "/api/v1/cases/" + cid
    revision_path = case_path + "/revisions/1"
    expect(received["state"] == "received" and received["revision"] is None
           and len(received["audit_events"]) == 1, "durable-reservation-after-timeout")
    expect(http(token, "GET", revision_path)[0] == 404, "no-partial-revision")
    restart_and_wait(token)
    expect(json.loads(http(token, "GET", case_path)[1]) == received, "pending-case-restart-recovery")
    print("PASS|live-cases|auth-key-contract|SQL-timeout-rollback|pending-case-survives-API-PostgreSQL-restart", flush=True)

    # Two actual concurrent HTTP submissions; exactly one performs calculation.
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: http(token, "POST", path, value, key), range(2)))
    expect(sorted(result[0] for result in results) == [200, 202], "concurrent-pending-and-completed")
    expect(all(json.loads(row[1])["case_id"] == cid for row in results), "concurrent-same-case-id")
    complete = json.loads(next(row[1] for row in results if row[0] == 200))
    expect(complete["state"] == "awaiting_approval" and complete["revision"] == 1
           and complete["approved"] is False and complete["published"] is False
           and len(complete["audit_events"]) == 2, "one-unapproved-revision")
    for _ in range(10):
        status, data, _ = http(token, "POST", path, value, key)
        expect(status == 200 and json.loads(data) == complete, "ten-completed-idempotent-replays")
    equivalent = dict(value, period_start_inclusive="2011-01-28T10:00:00+01:00",
                      period_end_exclusive="2011-01-28T11:00:00+01:00",
                      source_as_of_exclusive="2011-01-28T11:00:00+01:00")
    expect(json.loads(http(token, "POST", path, equivalent, key)[1]) == complete, "normalized-offset-equivalence")
    conflict = dict(value, source_as_of_exclusive="2011-01-28T11:00:00Z")
    status, data, _ = http(token, "POST", path, conflict, key)
    expect(status == 409 and b"postgresql" not in data, "changed-payload-idempotency-conflict")
    expect(http(None, "GET", case_path)[0] == 401 and http(None, "GET", revision_path)[0] == 401, "protected-draft")
    expect(http(token, "GET", "/api/v1/reports/" + cid)[0] == 404, "no-published-report-route")
    status, original, headers = http(token, "GET", revision_path)
    expect(status == 200 and headers.get("x-report-status") == "unapproved-draft", "draft-only-revision-route")
    expect(sha256(original).hexdigest() == complete["payload_sha256"], "exact-UTF8-payload-hash")
    report = json.loads(original, parse_float=Decimal)
    expect(report["current_period"]["kpis"]["sales_value_gbp"] == Decimal("1349.45")
           and report["prior_period"]["kpis"]["sales_value_gbp"] == Decimal("778.71")
           and report["changes"]["sales_value_gbp"]["relative_change"] == Decimal("0.73293010234875627641"),
           "persisted-M02-exact-arithmetic")
    print("PASS|live-cases|concurrent-200-202|ten-replays|offset-equivalence|changed-payload-409|M02-exact-hash", flush=True)

    restart_and_wait(token)
    expect(json.loads(http(token, "GET", case_path)[1]) == complete, "completed-case-restart")
    expect(http(token, "GET", revision_path)[1] == original, "revision-byte-identical-after-restart")
    expect(json.loads(http(token, "POST", path, value, key)[1]) == complete, "replay-after-restart")
    counts = docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-q", "-A", "-t",
        "-U", "g0_user", "-d", "raa_wp2_validation", "-c",
        "SELECT (SELECT count(*) FROM retail.report_cases WHERE case_id='" + cid + "'), "
        "(SELECT count(*) FROM retail.report_revisions WHERE case_id='" + cid + "'), "
        "(SELECT count(*) FROM retail.report_audit_events WHERE case_id='" + cid + "');"])
    expect(counts == "1|1|2", "actual-case-revision-audit-counts")
    print("PASS|completed-case-and-revision-survive-API-PostgreSQL-restart|counts-1-1-2|case_id=" + cid, flush=True)


if __name__ == "__main__":
    try:
        main()
    except CheckFailure as error:
        raise SystemExit("FAIL|" + str(error)) from None
    except Exception:
        raise SystemExit("FAIL|live-case-check|details-suppressed-to-protect-secrets") from None
