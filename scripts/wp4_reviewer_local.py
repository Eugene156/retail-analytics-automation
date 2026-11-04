"""Provision/check the sole owner's separate read-only bearer access.

Runtime secrets are exclusive ignored files, never argv, stdout or URLs.
No report decision, renewal, browser session or publication is implemented.
"""
import argparse
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import re
from uuid import UUID, uuid4
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from wp2_api_local import ROOT, SECRET_DIR, docker

OWNER_DIR = ROOT / ".local" / "wp4-reviewer"
CREDENTIAL = OWNER_DIR / "credential.json"
DSN = SECRET_DIR / "reviewer-dsn"
CASE = "61b10574-c842-4dae-8e8b-647f0d51ba55"


def credentials():
    value = json.loads(CREDENTIAL.read_text(encoding="utf-8"))
    if set(value) != {"reviewer_id", "token"} or not re.fullmatch(r"[a-f0-9]{64}", value["token"]):
        raise ValueError("Invalid owner credential")
    identity = UUID(value["reviewer_id"])
    if not identity.int or str(identity) != value["reviewer_id"]:
        raise ValueError("Invalid owner identity")
    service = (SECRET_DIR / "token").read_text(encoding="utf-8").strip()
    if value["token"] == service:
        raise ValueError("Owner and service credentials must differ")
    return value


def secret_values():
    values = []
    if CREDENTIAL.exists():
        value = credentials()
        values.extend((value["token"], sha256(value["token"].encode("ascii")).hexdigest(),
                       CREDENTIAL.read_text(encoding="utf-8").strip()))
    if DSN.exists():
        value = DSN.read_text(encoding="utf-8").strip()
        match = re.fullmatch(r"postgresql://raa_wp4_reviewer_api:([a-f0-9]{64})@raa-g0-postgres-1:5432/raa_wp2_validation", value)
        if not match:
            raise ValueError("Invalid reviewer connection")
        values.extend((value, match.group(1)))
    return values


def bootstrap():
    import secrets
    guard = docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
        "-U", "g0_user", "-d", "raa_wp2_validation", "-c",
        "SELECT EXISTS(SELECT 1 FROM retail.schema_migrations WHERE version=16 AND name='owner_read_auth') "
        "AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname='raa_wp4_reviewer_api' AND NOT rolsuper "
        "AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolbypassrls);"])
    if guard != "t" or not SECRET_DIR.is_dir():
        raise RuntimeError("Migration 016 and existing API configuration required")
    if CREDENTIAL.exists() != DSN.exists():
        raise RuntimeError("Partial owner configuration; not overwritten")
    if not CREDENTIAL.exists():
        empty = docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-qAt", "-U", "g0_user",
            "-d", "raa_wp2_validation", "-c",
            "SELECT NOT EXISTS(SELECT 1 FROM retail.owner_credentials) AND NOT EXISTS(SELECT 1 FROM retail.approval_policies);"])
        if empty != "t":
            raise RuntimeError("Existing database mapping without local files; not replaced")
        OWNER_DIR.mkdir(parents=True, exist_ok=True)
        with CREDENTIAL.open("x", encoding="utf-8") as stream:
            json.dump({"reviewer_id": str(uuid4()), "token": secrets.token_hex(32)}, stream)
        with DSN.open("x", encoding="utf-8") as stream:
            stream.write("postgresql://raa_wp4_reviewer_api:" + secrets.token_hex(32)
                         + "@raa-g0-postgres-1:5432/raa_wp2_validation\n")
    value = credentials()
    connection = DSN.read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"postgresql://raa_wp4_reviewer_api:([a-f0-9]{64})@raa-g0-postgres-1:5432/raa_wp2_validation", connection)
    if not match:
        raise ValueError("Invalid reviewer connection")
    identity, digest = value["reviewer_id"], sha256(value["token"].encode("ascii")).hexdigest()
    # All interpolated values have exact UUID/lowercase-hex validation. Stdin
    # and captured error streams prevent credentials from entering process argv.
    sql = f"""BEGIN;
    LOCK TABLE retail.owner_credentials, retail.approval_policies IN EXCLUSIVE MODE;
    DO $guard$ BEGIN
      IF EXISTS(SELECT 1 FROM retail.owner_credentials WHERE reviewer_id <> '{identity}'::uuid
          OR token_sha256 <> '{digest}' OR revoked_at IS NOT NULL)
         OR EXISTS(SELECT 1 FROM retail.approval_policies WHERE policy_version <> 'local-publication-v1'
          OR reviewer_id <> '{identity}'::uuid OR ttl_seconds <> 86400) THEN
        RAISE EXCEPTION 'Existing owner configuration differs; not overwritten';
      END IF;
    END $guard$;
    INSERT INTO retail.owner_credentials(reviewer_id,token_sha256) VALUES ('{identity}','{digest}')
      ON CONFLICT(singleton) DO NOTHING;
    INSERT INTO retail.approval_policies VALUES ('local-publication-v1','{identity}',86400)
      ON CONFLICT(policy_version) DO NOTHING;
    ALTER ROLE raa_wp4_reviewer_api LOGIN PASSWORD '{match.group(1)}';
    COMMIT;"""
    docker(["exec", "-i", "raa-g0-postgres-1", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
            "-U", "g0_user", "-d", "raa_wp2_validation", "-f", "-"], sql)
    print("PASS|owner-read-bootstrap|separate-credential|server-mapped-owner|86400-seconds|decisions-disabled")


def revoke():
    value = credentials()
    identity, digest = value["reviewer_id"], sha256(value["token"].encode("ascii")).hexdigest()
    sql = f"""BEGIN; DO $guard$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM retail.owner_credentials WHERE reviewer_id='{identity}'::uuid
          AND token_sha256='{digest}') THEN RAISE EXCEPTION 'Owner mapping differs'; END IF;
    END $guard$;
    UPDATE retail.owner_credentials SET revoked_at=clock_timestamp()
      WHERE reviewer_id='{identity}'::uuid AND token_sha256='{digest}' AND revoked_at IS NULL;
    COMMIT;"""
    docker(["exec", "-i", "raa-g0-postgres-1", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
            "-U", "g0_user", "-d", "raa_wp2_validation", "-f", "-"], sql)
    print("PASS|owner-credential-revoked|history-retained|no-reenable")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http(path, token=None, method="GET", headers=None, body=None):
    if not path.startswith(("/review/", "/api/", "/openapi.json")) or "?" in path:
        raise ValueError("Fixed local review path required")
    request_headers = dict(headers or {})
    if token is not None:
        request_headers["Authorization"] = "Bearer " + token
    data = None if body is None else json.dumps(body).encode("utf-8")
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request("http://127.0.0.1:18081" + path, headers=request_headers, method=method, data=data)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        body = response.read(524289)
        if len(body) > 524288 or any(v.encode() in body for v in secret_values()):
            raise RuntimeError("Response size/privacy guard failed")
        return response.status, body, response.headers


def check():
    owner = credentials()
    service = (SECRET_DIR / "token").read_text(encoding="utf-8").strip()
    status, body, headers = http("/review/v1/identity", owner["token"])
    value = json.loads(body)
    if status != 200 or value != {"reviewer_id": owner["reviewer_id"], "access": "read-only",
            "approval_ttl_seconds": 86400, "decision_enabled": False, "published": False}:
        raise RuntimeError("Owner identity check failed")
    if headers.get("Cache-Control") != "no-store":
        raise RuntimeError("Private response cache guard failed")
    for token in (None, "wrong", service):
        if http("/review/v1/identity", token)[0] != 401:
            raise RuntimeError("Owner/service separation check failed")
    connection = HTTPConnection("127.0.0.1", 18081, timeout=15)
    try:
        connection.putrequest("GET", "/review/v1/identity")
        connection.putheader("Authorization", "Bearer " + owner["token"])
        connection.putheader("Authorization", "Bearer " + owner["token"])
        connection.endheaders()
        response = connection.getresponse()
        duplicate_body = response.read(8193)
        if response.status != 401 or len(duplicate_body) > 8192 or any(v.encode() in duplicate_body for v in secret_values()):
            raise RuntimeError("Duplicate header/private response guard failed")
    finally:
        connection.close()
    origin = http("/review/v1/identity", owner["token"], headers={"Origin": "https://untrusted.invalid"})
    if origin[2].get("Access-Control-Allow-Origin") is not None or origin[2].get("Set-Cookie") is not None:
        raise RuntimeError("Unexpected browser credential allowance")
    for path in ("/api/v1/cases/" + CASE, "/openapi.json"):
        if http(path, owner["token"])[0] != 401:
            raise RuntimeError("Owner credential gained service access")
    before = http("/api/v1/cases/" + CASE, service)
    draft_before = http("/api/v1/cases/" + CASE + "/revisions/1", service)
    if before[0] != 200 or draft_before[0] != 200:
        raise RuntimeError("Stored fixture unavailable")
    if http("/review/v1/cases/" + CASE, owner["token"])[1] != before[1]:
        raise RuntimeError("Owner projection changed case")
    preview = http("/review/v1/cases/" + CASE + "/revisions/1/preview", owner["token"])
    if preview[0] != 200 or preview[2].get("X-Report-Status") != "unapproved-draft":
        raise RuntimeError("Owner preview unavailable")
    for path in ("/review/v1/identity", "/review/v1/cases/" + CASE + "/decision",
                 "/review/v1/cases/" + CASE + "/approval-proposal"):
        if http(path, owner["token"], "POST")[0] != 405:
            raise RuntimeError("Read-only method guard failed")
    if http("/review/v1/cases/" + CASE + "/approval-proposal", owner["token"])[0] != 404:
        raise RuntimeError("Unexpected live proposal; this pre-issuance check is not applicable")
    if http("/api/v1/cases/" + CASE, service)[1] != before[1] or http(
            "/api/v1/cases/" + CASE + "/revisions/1", service)[1] != draft_before[1]:
        raise RuntimeError("Read-only inspection mutated case/report")
    print("PASS|owner-read-http|identity|service-separation|preview|no-decisions|unchanged-case-and-report")


def database_check():
    value = credentials()
    private_input = json.dumps({"reviewer_id": value["reviewer_id"],
        "digest": sha256(value["token"].encode("ascii")).hexdigest()})
    docker(["exec", "-i", "-e", "RAA_RUN_REVIEWER_DB_TESTS=1", "raa-wp2-api", "python",
        "-m", "unittest", "discover", "-s", "tests", "-p", "test_wp4_reviewer_database.py", "-v"], private_input)
    print("PASS|three-actual-owner-database-tests|private-stdin|read-only-role|server-identity|unchanged-draft")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bootstrap", "check", "database-check", "revoke"))
    args = parser.parse_args()
    try:
        {"bootstrap": bootstrap, "check": check, "database-check": database_check, "revoke": revoke}[args.action]()
    except (RuntimeError, ValueError, OSError, TypeError, KeyError):
        raise SystemExit("FAIL|owner-read-operation|details-suppressed-to-protect-secrets") from None
