"""Run inside the demo API container; real Ollama tool call, no credentials."""
import json
import time
import urllib.request


def request(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


started = time.monotonic()
base = "http://raa-p2-demo-ollama-1:11434"
model = "qwen3:4b-instruct"
tags = request(base + "/api/tags")
assert model in [item["name"] for item in tags["models"]]
capabilities = request(base + "/api/show", {"model": model})["capabilities"]
assert "tools" in capabilities
messages = [
    {"role": "system", "content": "Use the provided tool to check the current demo API health. Never invent a service status."},
    {"role": "user", "content": "Check whether the demo API is healthy right now."},
]
tool = {"type": "function", "function": {
    "name": "get_demo_api_health",
    "description": "Read the actual current demo FastAPI health status.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}}
payload = {"model": model, "messages": messages, "tools": [tool],
           "stream": False, "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 256}}
first = request(base + "/api/chat", payload)
calls = first["message"].get("tool_calls", [])
assert len(calls) == 1, "Expected one actual tool call"
assert calls[0]["function"]["name"] == "get_demo_api_health"
assert calls[0]["function"]["arguments"] == {}
actual_health = request("http://127.0.0.1:8000/healthz")
messages.append(first["message"])
messages.append({"role": "tool", "tool_name": "get_demo_api_health",
                 "content": json.dumps(actual_health)})
final = request(base + "/api/chat", payload)
assert not final["message"].get("tool_calls"), "Unexpected repeated tool call"
assert final["message"].get("content", "").strip(), "Missing final model response"
print(json.dumps({"status": "PASS", "model": model, "capabilities": capabilities,
                  "tool_calls": calls, "actual_tool_result": actual_health,
                  "model_response": final["message"]["content"],
                  "elapsed_seconds": round(time.monotonic() - started, 2)}))
