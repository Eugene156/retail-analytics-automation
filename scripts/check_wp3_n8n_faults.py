"""Run actual n8n retry/rejection branches against a private HTTP test double.

Does not prove production API fault injection, approval or dead-letter persistence.
"""
from copy import deepcopy
import json

from wp3_n8n_local import (ROOT, N8N, CREDENTIAL_ID, CREDENTIAL_NAME, HTTP_NODES,
    CheckFailure, expect, invoke, sql, source_workflow, execute_workflow)

FIXTURE = "raa-wp3-http-test"
TEST_ID = "raa-wp3-http-fault-check-v1"
TEST_NAME = "WP3 Isolated HTTP Fault Check - Not a Product Workflow"
IMAGE_ID = "sha256:aaa61ac9d4ba0a80cbb539ec7b673e8fc1e17c1caa765482d8bb175387745cfb"


def fixture_request(method, path, value=None):
    # Execution in the existing API container reads the private mounted token;
    # no token value crosses argv, output or test workflow parameters.
    script = '''
import json
from pathlib import Path
from urllib.request import Request, urlopen
try:
    token = Path('/run/secrets/token').read_text().strip()
    request = Request('http://raa-wp3-http-test:8000' + PATH, method=METHOD,
        headers={'Authorization':'Bearer ' + token,'Content-Type':'application/json'},
        data=None if VALUE is None else json.dumps(VALUE).encode())
    with urlopen(request, timeout=10) as response:
        print(response.read().decode())
except Exception:
    raise SystemExit('FAIL|private-fixture-request|details-suppressed') from None
'''
    output = invoke(["exec", "-i", "raa-wp2-api", "python", "-"],
        "METHOD=" + repr(method) + "\nPATH=" + repr(path) + "\nVALUE=" + repr(value) + "\n" + script).stdout
    return json.loads(output)


def main():
    # This already verified case is intentionally reused in every test mode.
    result = invoke(["exec", "raa-g0-postgres-1", "psql", "-X", "-q", "-A", "-t", "-U", "g0_user",
        "-d", "raa_wp2_validation", "-c", "SELECT case_id FROM retail.report_cases "
        "WHERE idempotency_key='wp3-manual-m02-v1' AND state='awaiting_approval';"]).stdout.strip()
    from uuid import UUID
    cid = str(UUID(result))
    expect(FIXTURE not in invoke(["ps", "-a", "--format", "{{.Names}}"]).stdout.splitlines(), "fixture-name-unused")
    existing = sql("SELECT name FROM workflow_entity WHERE id='" + TEST_ID + "';")
    expect(existing in ("", TEST_NAME), "fault-workflow-ID-ownership")
    workflow = deepcopy(source_workflow())
    workflow.update(id=TEST_ID, name=TEST_NAME)
    for node in workflow["nodes"]:
        if node["name"] in HTTP_NODES:
            node["credentials"] = {"httpHeaderAuth": {"id": CREDENTIAL_ID, "name": CREDENTIAL_NAME}}
            node["parameters"]["url"] = node["parameters"]["url"].replace("http://raa-wp2-api:8000", "http://" + FIXTURE + ":8000")
    invoke(["exec", "-i", N8N, "n8n", "import:workflow", "--input=/dev/stdin"], json.dumps(workflow))
    invoke(["run", "--detach", "--name", FIXTURE, "--network", "raa-g0_default", "--label", "io.raa.test-scope=wp3-http",
        "--user", "65532:65532", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--memory", "128m", "--cpus", "0.25", "--pids-limit", "64", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "--mount", "type=bind,src=" + str(ROOT / "tests") + ",dst=/app/tests,readonly",
        "--mount", "type=bind,src=" + str(ROOT / ".local" / "wp2-api") + ",dst=/run/secrets,readonly",
        "--env", "RAA_WP3_FIXTURE_CASE_ID=" + cid, "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--entrypoint", "python", IMAGE_ID, "tests/wp3_http_fixture.py"])
    try:
        import time
        for _ in range(40):
            try:
                fixture_request("GET", "/__test/observations")
                break
            except CheckFailure as error:
                if str(error) != "docker-or-n8n-private-python":
                    raise
                time.sleep(0.25)
        else:
            raise CheckFailure("fixture-readiness")
        for scenario in ("retry_503", "pending_202", "exhaust_503", "permanent_401", "corrupt_draft", "swap_identity"):
            fixture_request("POST", "/__test/configure", {"scenario": scenario})
            code, execution = execute_workflow(TEST_ID)
            data = execution["data"]["resultData"]
            records = data.get("runData", {}).get("Evaluate request", [])
            evaluated = [record["data"]["main"][0][0]["json"] for record in records]
            observations = fixture_request("GET", "/__test/observations")
            posts = [item for item in observations["calls"] if item["method"] == "POST"]
            if scenario in ("retry_503", "pending_202"):
                expect(code == 0 and "error" not in data and data.get("lastNodeExecuted") == "Verified unapproved draft",
                       "test-double-retry-success")
                expect(len(posts) == 2 and posts[1]["seconds"] - posts[0]["seconds"] >= 2,
                       "actual-Retry-After-wait")
                expect([row["attempt"] for row in evaluated] == [1, 2], "actual-loop-attempt-index")
            else:
                expect(code != 0 and "error" in data, "fail-closed-test-execution")
                if scenario == "exhaust_503":
                    expect(len(posts) == 3 and evaluated[-1]["reason"] == "retry_exhausted_manual_recovery",
                           "actual-three-attempt-exhaustion")
                elif scenario == "permanent_401":
                    expect(len(posts) == 1 and evaluated[-1]["reason"] == "permanent_HTTP_failure", "permanent-no-retry")
                elif scenario == "swap_identity":
                    expect(len(posts) == 1 and evaluated[-1]["reason"] == "case_identity_mismatch", "identity-rejection")
                else:
                    expect(data.get("lastNodeExecuted") == "Verified unapproved draft" and len(posts) == 1,
                           "actual-binary-hash-rejection")
            print("PASS|actual-n8n-HTTP-test-double|" + scenario + "|POST-attempts=" + str(len(posts)), flush=True)
        invoke(["logs", FIXTURE])
    finally:
        # Exact helper-created container, checked label; never remove volumes.
        label = invoke(["inspect", FIXTURE, "--format", '{{index .Config.Labels "io.raa.test-scope"}}']).stdout.strip()
        expect(label == "wp3-http", "fixture-cleanup-scope")
        invoke(["stop", FIXTURE])
        invoke(["rm", FIXTURE])


if __name__ == "__main__":
    try:
        main()
    except CheckFailure as error:
        raise SystemExit("FAIL|" + str(error)) from None
    except Exception:
        raise SystemExit("FAIL|n8n-fault-check|details-suppressed-to-protect-secrets") from None
