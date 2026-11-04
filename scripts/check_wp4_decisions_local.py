"""Isolated schema-only decision tests; no real case decision or publication."""
import json
import re
import secrets
from uuid import uuid4
from wp2_api_local import ROOT, docker
from wp4_portal_local import DSN, DSN_PATTERN, retain


def main():
    database = "raa_wp4_portal_test_"+uuid4().hex[:12]
    portal = DSN.read_text(encoding="utf-8").strip()
    if not re.fullmatch(DSN_PATTERN, portal):
        raise RuntimeError("Configured portal required")
    password = docker(["exec", "raa-g0-postgres-1", "printenv", "POSTGRES_PASSWORD"])
    if not password or any(c in password for c in "\r\n"):
        raise RuntimeError("Configured database required")
    schema = docker(["exec", "raa-g0-postgres-1", "pg_dump", "-U", "g0_user", "-d", "raa_wp2_validation",
                     "--schema-only", "--schema=retail"])
    base = json.loads(docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-qAt", "-U", "g0_user",
        "-d", "raa_wp2_validation", "-c", "SELECT jsonb_build_object('request',request_identity,"
        "'report',retail.api_get_revision_v1(case_id,1)) FROM retail.report_cases "
        "WHERE case_id='61b10574-c842-4dae-8e8b-647f0d51ba55';"]))
    docker(["exec", "raa-g0-postgres-1", "createdb", "-U", "g0_user", database])
    print("Isolated database created: "+database)
    docker(["exec", "-i", "raa-g0-postgres-1", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
            "-1", "-U", "g0_user", "-d", database, "-f", "-"], schema)
    print("PASS|isolated-schema-copy")
    docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
        "-U", "g0_user", "-d", database, "-c",
        "INSERT INTO retail.schema_migrations(version,name) VALUES(19,'decision_outbox_foundation'); "
        "ALTER ROLE raa_wp4_portal_api IN DATABASE "+database+" SET default_transaction_read_only=on;"])
    migration = (ROOT/"db/migrations/020_portal_decision_projection.sql").read_text(encoding="utf-8")
    # Exact isolated database gate substitution, never a runtime guard change.
    gate = "current_database()<>'raa_wp2_validation'"
    if migration.count(gate)!=1:
        raise RuntimeError("Unexpected migration gate")
    docker(["exec", "-i", "raa-g0-postgres-1", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
        "-1", "-U", "g0_user", "-d", database, "-f", "-"], migration.replace(gate,"current_database()<>'"+database+"'"))
    print("PASS|isolated-migration-020")
    fixture = (ROOT/"db/tests/019_decision_outbox_foundation.sql").read_text(encoding="utf-8").split("DO $test$")[0]
    fixture = "\n".join(line for line in fixture.splitlines() if not line.startswith("\\"))
    owner = secrets.token_hex(32)
    retain(owner)
    arguments = {"database":database,"admin":{"host":"raa-g0-postgres-1","dbname":database,
        "user":"g0_user","password":password}, "portal_dsn":portal.rsplit('/',1)[0]+'/'+database,
        "fixture_sql":fixture,"base":base,"owner":owner}
    result = json.loads(docker(["exec", "-i", "raa-wp2-api", "python", "-c",
        "import runpy,sys; sys.path.insert(0,'/app/tests'); runpy.run_path('tests/test_wp4_decision_database.py',run_name='__main__')"],json.dumps(arguments)))
    for value in result.get("probe_values",[]):
        retain(value)
    print("Test database retained (synthetic identity, no source rows): "+database)
    if not result.get("passed"):
        # Only fixed test names/counts, never tracebacks, SQL, DSNs or credentials.
        print("FAIL|isolated-decision-tests|"+str(result.get("tests_run",0))+"|"+','.join(result.get("failed_tests",[])))
        raise RuntimeError("Isolated tests failed; private details suppressed")
    print("PASS|isolated-decision-tests|"+str(result["tests_run"])+"|actual-scoped-login|two-concurrent-decisions|ten-replays|ASGI-real-DB|no-publication")


if __name__=="__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError):
        raise SystemExit("FAIL|decision-check|details-suppressed-to-protect-secrets") from None
