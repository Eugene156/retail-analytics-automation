"""Real loopback HTTP checks. Only aggregates/statuses are printed."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from http.client import HTTPConnection
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18081"
HASH = "BCBE73B35F5B7BABF197FB0CB983A11F5D9FF929078D4AA53D171B1F2DF2E980"


class CheckFailure(Exception):
    """Only predefined non-secret check labels may be printed."""


def http(token, method, path, payload=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if body is None and payload is not None:
        body = json.dumps(payload).encode()
    request = Request(BASE + path, data=body, headers=headers, method=method)
    try:
        response = urlopen(request, timeout=150)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), {key.lower(): value for key, value in response.headers.items()}


def expect(condition, label):
    if not condition:
        raise CheckFailure(label)


def payload(start="2011-01-28T09:00:00Z", end="2011-01-28T10:00:00Z"):
    return {"source_file_sha256": HASH, "source_time_interpretation": "Europe/London-assumed",
            "period_start_inclusive": start, "period_end_exclusive": end,
            "source_as_of_exclusive": end}


def main():
    token = (ROOT / ".local" / "wp2-api" / "token").read_text(encoding="utf-8").strip()
    path = "/api/v1/calculations/comparison"
    expect(http(None, "GET", "/healthz")[0] == 200, "health")
    for protected in ("/readyz", "/openapi.json"):
        expect(http(None, "GET", protected)[0] == 401, "protected-route")
    expect(http(None, "POST", path, body=b"{broken")[0] == 401, "anonymous-denial-before-parse")
    expect(http("wrong", "POST", path, payload())[0] == 401, "wrong-token")
    expect(http(token, "GET", "/readyz")[0] == 200, "ready")
    status, data, _ = http(token, "GET", "/openapi.json")
    expect(status == 200, "openapi")
    schema = json.loads(data)
    expect(schema["paths"][path]["post"]["security"] == [{"CalculationToken": []}], "openapi-security")
    expect(http(token, "POST", path, body=b"x" * 8193)[0] == 413, "actual-body-limit")
    connection = HTTPConnection("127.0.0.1", 18081, timeout=5)
    try:
        connection.request("POST", path, body=iter([b"x" * 4096] * 3),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            encode_chunked=True)
        expect(connection.getresponse().status == 413, "chunked-body-limit")
    finally:
        connection.close()
    invalid = [
        dict(payload(), period_start_inclusive="2011-01-28T09:00:00"),
        dict(payload(), source_as_of_exclusive="2011-01-28T09:30:00Z"),
        dict(payload(), secret="must-not-be-echoed", sql="DROP TABLE retail.source_rows"),
        payload("2009-12-03T09:00:00Z", "2009-12-03T10:00:00Z"),
        payload("2011-12-09T12:00:00Z", "2011-12-09T13:00:00Z"),
        payload("2011-10-30T01:30:00+01:00", "2011-10-30T02:30:00Z"),
    ]
    for value in invalid:
        status, data, _ = http(token, "POST", path, value)
        expect(status == 422 and b"must-not-be-echoed" not in data, "invalid-period-or-input")
    print("PASS|live-http|auth|health-ready|openapi|body-limit|offset-cutoff|range|DST|safe-errors", flush=True)

    # Observe an actual in-flight fixed SQL call before testing busy behavior.
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(http, token, "POST", path, payload())
        active = False
        for _ in range(10):
            result = subprocess.run(["docker", "exec", "raa-g0-postgres-1", "psql", "-X", "-q", "-A", "-t",
                "-U", "g0_user", "-d", "raa_wp2_validation", "-c",
                "SELECT count(*) FROM pg_stat_activity WHERE usename='raa_wp2_api' "
                "AND state='active' AND query LIKE '%SELECT retail.api_comparison_report_v1%';"],
                capture_output=True, text=True, check=False)
            if result.returncode == 0 and result.stdout.strip() == "1":
                active = True
                break
            if pending.done():
                break
            time.sleep(0.1)
        expect(active, "in-flight-database-call-not-observed")
        status, _, headers = http(token, "POST", path, payload())
        expect(status == 429 and headers.get("retry-after") == "5", "single-flight-busy")
        status, data, headers = pending.result()
    expect(status == 200 and headers.get("content-type") == "application/json", "M02-http")
    report = json.loads(data, parse_float=Decimal)
    current = report["current_period"]["kpis"]
    prior = report["prior_period"]["kpis"]
    sales = report["changes"]["sales_value_gbp"]
    expect(current["period_source_rows"] == 74 and prior["period_source_rows"] == 43, "M02-source-counts")
    expect(sales["current_value"] == Decimal("1349.45") and sales["prior_value"] == Decimal("778.71"), "M02-money")
    expect(sales["relative_change"] == Decimal("0.73293010234875627641"), "M02-exact-numeric-text")
    print("PASS|live-http|M02|current-rows=74|prior-rows=43|current-sales=1349.45|prior-sales=778.71|exact-ratio|busy-429", flush=True)

    status, data, _ = http(token, "POST", path, payload("2011-01-01T00:00:00Z", "2011-01-01T01:00:00Z"))
    expect(status == 200, "M10-http")
    report = json.loads(data, parse_float=Decimal)
    expect(all(c["relative_change"] is None and c["relative_change_status"] == "zero_baseline"
               for c in report["changes"].values()), "M10-zero-baseline")
    expect(report["current_period"]["kpis"]["period_source_rows"] == 0, "M10-empty")
    print("PASS|live-http|M10|empty-current-prior|six-zero-baseline-flags|no-model-call", flush=True)


if __name__ == "__main__":
    try:
        main()
    except CheckFailure as error:
        raise SystemExit("FAIL|live-api-check|" + str(error)) from None
    except Exception:
        # Deliberately avoid exception/connection/header dumps containing secrets.
        raise SystemExit("FAIL|live-api-check|details-suppressed-to-protect-secrets") from None
