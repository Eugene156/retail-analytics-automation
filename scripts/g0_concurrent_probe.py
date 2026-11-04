"""Load the trial model once while the G0 stack is running for memory sampling."""

import json
import time
import urllib.request


payload = {
    "model": "qwen3:4b-instruct",
    "stream": False,
    "keep_alive": "5m",
    "messages": [
        {"role": "system", "content": "Return a short factual JSON answer only."},
        {"role": "user", "content": "What is 7 times 6?"},
    ],
    "format": {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
    "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 40},
}
request = urllib.request.Request(
    "http://127.0.0.1:11434/api/chat",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
start = time.monotonic()
with urllib.request.urlopen(request, timeout=90) as response:
    result = json.load(response)
answer = json.loads(result["message"]["content"])["answer"]
if answer != 42:
    raise SystemExit("FAIL: local model returned an unexpected answer")
print(f"PASS: bounded concurrent model request; answer=42; elapsed={time.monotonic()-start:.3f}s")
