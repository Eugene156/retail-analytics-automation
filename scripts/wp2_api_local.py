"""Bootstrap/start the bounded API using the existing verified dependency image.

Secrets are generated only under ignored .local; never printed or passed in argv.
No package/image installation, volume reset or G0 service modification occurs.
"""
import argparse
from pathlib import Path
import re
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SECRET_DIR = ROOT / ".local" / "wp2-api"
CONTAINER = "raa-wp2-api"
IMAGE_ID = "sha256:aaa61ac9d4ba0a80cbb539ec7b673e8fc1e17c1caa765482d8bb175387745cfb"


def docker(arguments, input_text=None):
    result = subprocess.run(["docker", *arguments], input=input_text,
                            text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Local Docker operation failed; secret output suppressed")
    return result.stdout.strip()


def bootstrap():
    guard = docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-q", "-A", "-t",
                    "-v", "ON_ERROR_STOP=1", "-U", "g0_user", "-d", "raa_wp2_validation", "-c",
                    "SELECT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version=12 "
                    "AND name='comparison_api_boundary') AND EXISTS (SELECT 1 FROM pg_roles "
                    "WHERE rolname='raa_wp2_api' AND NOT rolsuper AND NOT rolcreatedb "
                    "AND NOT rolcreaterole AND NOT rolbypassrls);"])
    if guard != "t":
        raise RuntimeError("Apply migration 012 to the isolated database first")
    token_path, dsn_path = SECRET_DIR / "token", SECRET_DIR / "dsn"
    if token_path.exists() != dsn_path.exists():
        raise RuntimeError("Partial secret configuration: inspect locally, do not overwrite")
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        dsn = dsn_path.read_text(encoding="utf-8").strip()
        match = re.fullmatch(r"postgresql://raa_wp2_api:([a-f0-9]{64})@raa-g0-postgres-1:5432/raa_wp2_validation", dsn)
        if not re.fullmatch(r"[a-f0-9]{64}", token) or not match:
            raise RuntimeError("Existing secret configuration is invalid; not overwritten")
        password = match.group(1)
    else:
        token, password = secrets.token_hex(32), secrets.token_hex(32)
        SECRET_DIR.mkdir(parents=True, exist_ok=True)
        # Runtime secret generation, not repository source editing. Exclusive
        # creation preserves existing credentials; inherited Windows ACLs apply.
        with token_path.open("x", encoding="utf-8") as stream:
            stream.write(token + "\n")
        with dsn_path.open("x", encoding="utf-8") as stream:
            stream.write(f"postgresql://raa_wp2_api:{password}@raa-g0-postgres-1:5432/raa_wp2_validation\n")
    docker(["exec", "-i", "raa-g0-postgres-1", "psql", "-X", "-q",
            "-v", "ON_ERROR_STOP=1", "-U", "g0_user", "-d", "raa_wp2_validation", "-f", "-"],
           "BEGIN; ALTER ROLE raa_wp2_api LOGIN PASSWORD '" + password + "'; COMMIT;")
    print("PASS|api-secret-bootstrap|dedicated-role|no-secret-output")


def start():
    if not all((SECRET_DIR / name).is_file() for name in ("token", "dsn", "case-dsn")):
        raise RuntimeError("Bootstrap API secrets first")
    image_id = docker(["image", "inspect", "raa-g0-api:latest", "--format", "{{.Id}}"])
    if image_id != IMAGE_ID:
        raise RuntimeError("Existing G0 image differs from the verified local image")
    containers = docker(["ps", "-a", "--format", "{{.Names}}"]).splitlines()
    if CONTAINER in containers:
        raise RuntimeError("API container already exists; inspect it instead of replacing it")
    docker(["run", "--detach", "--name", CONTAINER, "--network", "raa-g0_default",
            "--user", "65532:65532", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit", "128", "--memory", "512m",
            "--cpus", "1", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--publish", "127.0.0.1:18081:8000",
            "--mount", f"type=bind,src={ROOT / 'api'},dst=/app/api,readonly",
            "--mount", f"type=bind,src={ROOT / 'tests'},dst=/app/tests,readonly",
            "--mount", f"type=bind,src={SECRET_DIR},dst=/run/secrets,readonly",
            "--env", "RAA_API_TOKEN_FILE=/run/secrets/token",
            "--env", "RAA_DATABASE_DSN_FILE=/run/secrets/dsn",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint", "python", image_id, "-m", "uvicorn", "api.main:application",
            "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"])
    print("PASS|api-started|loopback-18081|read-only-container|one-worker")


def bootstrap_cases():
    guard = docker(["exec", "raa-g0-postgres-1", "psql", "-X", "-q", "-A", "-t",
        "-v", "ON_ERROR_STOP=1", "-U", "g0_user", "-d", "raa_wp2_validation", "-c",
        "SELECT EXISTS (SELECT 1 FROM retail.schema_migrations WHERE version=13 "
        "AND name='report_requests') AND EXISTS (SELECT 1 FROM pg_roles "
        "WHERE rolname='raa_wp2_case_api' AND NOT rolsuper AND NOT rolcreatedb "
        "AND NOT rolcreaterole AND NOT rolbypassrls);"])
    if guard != "t" or not (SECRET_DIR / "token").is_file() or not (SECRET_DIR / "dsn").is_file():
        raise RuntimeError("Apply migration 013 and bootstrap calculation secrets first")
    path = SECRET_DIR / "case-dsn"
    if path.exists():
        dsn = path.read_text(encoding="utf-8").strip()
        match = re.fullmatch(r"postgresql://raa_wp2_case_api:([a-f0-9]{64})@raa-g0-postgres-1:5432/raa_wp2_validation", dsn)
        if not match:
            raise RuntimeError("Existing case secret is invalid; not overwritten")
        password = match.group(1)
    else:
        password = secrets.token_hex(32)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(f"postgresql://raa_wp2_case_api:{password}@raa-g0-postgres-1:5432/raa_wp2_validation\n")
    docker(["exec", "-i", "raa-g0-postgres-1", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
        "-U", "g0_user", "-d", "raa_wp2_validation", "-f", "-"],
        "BEGIN; ALTER ROLE raa_wp2_case_api LOGIN PASSWORD '" + password + "'; COMMIT;")
    print("PASS|case-secret-bootstrap|separate-scoped-write-role|no-secret-output")


def check_secrets():
    from wp4_reviewer_local import secret_values
    from wp4_portal_local import secret_values as portal_secrets
    token = (SECRET_DIR / "token").read_text(encoding="utf-8").strip()
    dsn = (SECRET_DIR / "dsn").read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"postgresql://raa_wp2_api:([a-f0-9]{64})@raa-g0-postgres-1:5432/raa_wp2_validation", dsn)
    if not re.fullmatch(r"[a-f0-9]{64}", token) or not match:
        raise RuntimeError("Invalid local secrets")
    values = [token, dsn, match.group(1)]
    case_path = SECRET_DIR / "case-dsn"
    if case_path.exists():
        case_dsn = case_path.read_text(encoding="utf-8").strip()
        case_match = re.fullmatch(r"postgresql://raa_wp2_case_api:([a-f0-9]{64})@raa-g0-postgres-1:5432/raa_wp2_validation", case_dsn)
        if not case_match:
            raise RuntimeError("Invalid local case secret")
        values.extend((case_dsn, case_match.group(1)))
    values.extend(secret_values())
    values.extend(portal_secrets())
    for container in (CONTAINER, "raa-g0-postgres-1"):
        result = subprocess.run(["docker", "logs", container], capture_output=True, text=True, check=False)
        if result.returncode or any(value in result.stdout + result.stderr
                                    for value in values):
            raise RuntimeError("Local log secret check failed; values suppressed")
    print("PASS|api-postgres-logs|no-new-runtime-token-password-dsn")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["bootstrap", "bootstrap-cases", "start", "check-secrets"])
    arguments = parser.parse_args()
    try:
        {"bootstrap": bootstrap, "bootstrap-cases": bootstrap_cases,
         "start": start, "check-secrets": check_secrets}[arguments.action]()
    except (RuntimeError, OSError):
        raise SystemExit("FAIL|local-api-operation|details-suppressed-to-protect-secrets") from None
