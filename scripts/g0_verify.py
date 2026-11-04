"""Verify G0 API authentication and persisted SQL probe without printing secrets."""

from pathlib import Path
import time
import urllib.error
import urllib.request


root = Path(__file__).resolve().parents[1]
values = dict(
    line.split("=", 1)
    for line in (root / ".local" / "g0" / ".env").read_text(encoding="utf-8").splitlines()
    if line and not line.startswith("#")
)
url = "http://127.0.0.1:18080/probe/g0-n8n"
deadline = time.monotonic() + 30
while True:
    try:
        with urllib.request.urlopen("http://127.0.0.1:18080/health", timeout=3):
            break
    except (urllib.error.URLError, ConnectionError):
        if time.monotonic() >= deadline:
            raise SystemExit("FAIL: API did not become ready within 30 seconds")
        time.sleep(0.5)
try:
    urllib.request.urlopen(url, timeout=10)
    raise SystemExit("FAIL: anonymous API read was allowed")
except urllib.error.HTTPError as error:
    if error.code != 401:
        raise SystemExit(f"FAIL: anonymous API read returned {error.code}")
request = urllib.request.Request(
    url, headers={"Authorization": "Bearer " + values["G0_API_TOKEN"]}
)
with urllib.request.urlopen(request, timeout=10) as response:
    import json

    result = json.load(response)
if result != {"key": "g0-n8n", "value": 42}:
    raise SystemExit("FAIL: persisted SQL value mismatch")
print("PASS: anonymous request rejected (401); authenticated SQL read returned value 42.")
