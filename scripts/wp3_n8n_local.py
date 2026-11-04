"""Import/execute/export-check a scoped manual draft workflow in existing n8n.

Uses existing images/volumes. Secrets travel to encrypted credentials by stdin,
never argv, workflow parameters, printed execution results or repository files.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "wp3_manual_draft.json"
WORKFLOW_ID = "raa-wp3-manual-draft-v1"
CREDENTIAL_ID = "raa-wp3-case-api-auth"
CREDENTIAL_NAME = "Retail Analytics draft API"
N8N = "raa-g0-n8n-1"
PG = "raa-g0-postgres-1"
IMAGE_ID = "sha256:fba7e81fa077ad8b6486804fec33a962ab44a64ce9e3bc8d488465b0f8d65a52"
HTTP_NODES = {"Submit request", "Read case", "Read unapproved draft"}


class CheckFailure(Exception):
    """Only predefined safe labels are printable."""


def expect(condition, label):
    if not condition:
        raise CheckFailure(label)


def secrets_to_protect():
    from wp4_reviewer_local import secret_values
    from wp4_portal_local import secret_values as portal_secrets
    values = []
    for name in ("token", "dsn", "case-dsn"):
        path = ROOT / ".local" / "wp2-api" / name
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            values.append(value)
            match = re.search(r":([a-f0-9]{64})@", value)
            if match:
                values.append(match.group(1))
    path = ROOT / ".local" / "g0" / ".env"
    if path.exists():
        values.extend(line.split("=", 1)[1] for line in path.read_text(encoding="utf-8").splitlines()
                      if line and not line.startswith("#") and "=" in line)
    values.extend(secret_values())
    values.extend(portal_secrets())
    return [value for value in values if value]


def invoke(arguments, stdin=None, allow_failure=False, timeout=650):
    result = subprocess.run(["docker", *arguments], input=stdin, text=True,
                            capture_output=True, check=False, timeout=timeout)
    expect(not any(secret in result.stdout + result.stderr for secret in secrets_to_protect()),
           "captured-output-secret-check")
    if not allow_failure:
        if result.returncode:
            # Safe, finite stage labels; never print CLI/Docker error streams.
            stage = "command"
            if arguments and arguments[0] in ("run", "stop", "start", "rm", "inspect", "logs"):
                stage = arguments[0]
            elif "import:workflow" in arguments:
                stage = "workflow-import"
            elif "import:credentials" in arguments:
                stage = "credential-import"
            elif "python" in arguments:
                stage = "private-python"
            elif "psql" in arguments:
                stage = "metadata-query"
            raise CheckFailure("docker-or-n8n-" + stage)
    return result


def sql(query):
    return invoke(["exec", PG, "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                   "-U", "g0_user", "-d", "n8n", "-c", query]).stdout.strip()


def extract_json(output, predicate):
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except (ValueError, json.JSONDecodeError):
            continue
        if predicate(value):
            return value
    raise CheckFailure("structured-cli-output")


def source_workflow():
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    expect(workflow["id"] == WORKFLOW_ID and workflow.get("active") is False, "scoped-inactive-workflow")
    expect(not any(secret in json.dumps(workflow) for secret in secrets_to_protect()), "source-secret-check")
    expect(all("credentials" not in node for node in workflow["nodes"]), "sanitized-source-credential-bindings")
    return workflow


def guard():
    expect(invoke(["inspect", N8N, "--format", "{{.Image}}"]).stdout.strip() == IMAGE_ID, "pinned-n8n-image")
    token = (ROOT / ".local" / "wp2-api" / "token").read_text(encoding="utf-8").strip()
    expect(re.fullmatch(r"[a-f0-9]{64}", token) is not None, "local-token-format")
    with urlopen(Request("http://127.0.0.1:18081/readyz", headers={"Authorization": "Bearer " + token}), timeout=10) as response:
        expect(response.status == 200, "API-readiness")
    existing = sql("SELECT name FROM workflow_entity WHERE id='" + WORKFLOW_ID + "';")
    expect(existing in ("", source_workflow()["name"]), "workflow-ID-ownership")


def setup():
    guard()
    existing = sql("SELECT name || '|' || type FROM credentials_entity WHERE id='" + CREDENTIAL_ID + "';")
    expect(existing in ("", CREDENTIAL_NAME + "|httpHeaderAuth"), "credential-ID-ownership")
    if not existing:
        token = (ROOT / ".local" / "wp2-api" / "token").read_text(encoding="utf-8").strip()
        credential = [{"id": CREDENTIAL_ID, "name": CREDENTIAL_NAME, "type": "httpHeaderAuth",
                       "data": {"name": "Authorization", "value": "Bearer " + token}}]
        invoke(["exec", "-i", N8N, "n8n", "import:credentials", "--input=/dev/stdin"], json.dumps(credential))
    # Existing credentials are preserved, never blindly rotated.
    workflow = source_workflow()
    for node in workflow["nodes"]:
        if node["name"] in HTTP_NODES:
            node["credentials"] = {"httpHeaderAuth": {"id": CREDENTIAL_ID, "name": CREDENTIAL_NAME}}
    invoke(["exec", "-i", N8N, "n8n", "import:workflow", "--input=/dev/stdin"], json.dumps(workflow))
    expect(sql("SELECT active FROM workflow_entity WHERE id='" + WORKFLOW_ID + "';") == "f", "inactive-after-import")
    print("PASS|n8n-scoped-import|encrypted-credential-stdin|inactive-manual-only|no-secret-output")


def execute_workflow(workflow_id=WORKFLOW_ID):
    expect(re.fullmatch(r"raa-wp3-[a-z0-9-]+", workflow_id) is not None, "execution-ID-scope")
    expect(sql("SELECT count(*) FROM workflow_entity WHERE active;") == "0", "no-active-workflow-before-cli")
    expect(sql("SELECT count(*) FROM execution_entity WHERE status IN ('running','waiting','new');") == "0",
           "no-inflight-execution-before-cli")
    running = invoke(["inspect", N8N, "--format", "{{.State.Running}}"]).stdout.strip() == "true"
    if running:
        invoke(["stop", N8N])
    try:
        # The tested G0 CLI path needs the n8n network alias for its external
        # runner and exclusive broker port. No sandbox/env-access relaxation.
        result = invoke(["compose", "--env-file", str(ROOT / ".local" / "g0" / ".env"),
            "-f", str(ROOT / "g0" / "compose.yaml"), "run", "--rm", "--no-deps", "--use-aliases", "-T",
            "n8n", "execute", "--id=" + workflow_id, "--rawOutput"], allow_failure=True)
    finally:
        if running:
            invoke(["start", N8N])
    result_json = extract_json(result.stdout, lambda value: isinstance(value, dict)
        and isinstance(value.get("data"), dict) and "resultData" in value["data"])
    return result.returncode, result_json


def run():
    guard()
    code, execution = execute_workflow()
    result = execution["data"]["resultData"]
    if code or "error" in result or result.get("lastNodeExecuted") != "Verified unapproved draft":
        allowed_nodes = {node["name"] for node in source_workflow()["nodes"]}
        last = result.get("lastNodeExecuted")
        diagnostics = {"last_node": last if last in allowed_nodes else "unknown", "cli_exit": code}
        error = result.get("error", {})
        name = error.get("name", "")
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z]+", name):
            diagnostics["error_type"] = name
        for record in result.get("runData", {}).get("Evaluate request", []):
            for item in record.get("data", {}).get("main", [[]])[0]:
                value = item.get("json", {})
                diagnostics.setdefault("attempts", []).append({key: value.get(key) for key in
                    ("attempt", "status_code", "reason")})
        for record in result.get("runData", {}).get("SHA256 exact draft bytes", []):
            for item in record.get("data", {}).get("main", [[]])[0]:
                value = item.get("json", {})
                for key in ("expected_payload_sha256", "actual_payload_sha256"):
                    if isinstance(value.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", value[key]):
                        diagnostics[key] = value[key]
                draft = value.get("draft_text")
                if isinstance(draft, str):
                    diagnostics["received_text_sha256"] = sha256(draft.encode()).hexdigest()
                    diagnostics["has_exact_known_M02_ratio"] = "0.73293010234875627641" in draft
        print("CHECK|safe-workflow-diagnostics|" + json.dumps(diagnostics, sort_keys=True))
    expect(code == 0 and "error" not in result and result.get("lastNodeExecuted") == "Verified unapproved draft",
           "live-manual-workflow-success")
    summary = result["runData"]["Verified unapproved draft"][0]["data"]["main"][0][0]["json"]
    expect(summary["status"] == "unapproved_draft_verified" and summary["revision"] == 1
           and summary["ai_mode"] == "disabled" and summary["publication"] == "not_enabled", "draft-only-summary")
    print("PASS|live-n8n-manual-draft|" + json.dumps(summary, sort_keys=True))


def export_check():
    guard()
    output = invoke(["exec", N8N, "n8n", "export:workflow", "--id=" + WORKFLOW_ID, "--output=/dev/stdout"]).stdout
    exported = extract_json(output, lambda value: isinstance(value, list) and len(value) == 1
                            and isinstance(value[0], dict) and value[0].get("id") == WORKFLOW_ID)[0]
    source = source_workflow()
    sanitized = deepcopy(exported)
    for node in sanitized["nodes"]:
        node.pop("credentials", None)
    expect(all(sanitized[key] == source[key] for key in ("id", "name", "nodes", "connections", "settings")),
           "live-export-source-roundtrip")
    expect(not sanitized.get("active") and not sanitized.get("pinData"), "inactive-unpinned-export")
    print("PASS|live-export-roundtrip|source-is-sanitized-tested-export|no-credential-references-or-values")


def check_logs():
    for container in (N8N, "raa-g0-runner-1", "raa-wp2-api", PG):
        invoke(["logs", container])
    print("PASS|targeted-four-container-logs|no-current-project-secret-values")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "run", "export-check", "check-logs"])
    args = parser.parse_args()
    try:
        {"setup": setup, "run": run, "export-check": export_check, "check-logs": check_logs}[args.action]()
    except CheckFailure as error:
        raise SystemExit("FAIL|" + str(error)) from None
    except Exception:
        raise SystemExit("FAIL|local-n8n-operation|details-suppressed-to-protect-secrets") from None
