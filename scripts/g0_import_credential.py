"""Import the local G0 API token to n8n's encrypted credential store via stdin."""

import json
from pathlib import Path
import subprocess


root = Path(__file__).resolve().parents[1]
env_path = root / ".local" / "g0" / ".env"
values = dict(
    line.split("=", 1)
    for line in env_path.read_text(encoding="utf-8").splitlines()
    if line and not line.startswith("#")
)
payload = [
    {
        "id": "g0-local-api-auth",
        "name": "G0 local API",
        "type": "httpHeaderAuth",
        "data": {
            "name": "Authorization",
            "value": "Bearer " + values["G0_API_TOKEN"],
        },
    }
]
result = subprocess.run(
    [
        "docker",
        "exec",
        "-i",
        "raa-g0-n8n-1",
        "n8n",
        "import:credentials",
        "--input=/dev/stdin",
    ],
    input=json.dumps(payload).encode("utf-8"),
    capture_output=True,
    check=False,
)
if result.returncode:
    # CLI failures can contain input details; do not echo captured streams.
    raise SystemExit("Credential import failed; CLI output withheld to protect the token.")
print("G0 API credential imported; secret was not displayed.")
