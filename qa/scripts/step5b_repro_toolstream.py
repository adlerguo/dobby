import http.client
import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "qa" / "env"
BASE = "http://localhost:8001/api/v1"


def req(method, path, *, json_body=None, token=None):
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_sse(raw):
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = None
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        try:
            payload = json.loads(data)
        except Exception:
            payload = data
        events.append({"event": event, "data": payload})
    return events


def main():
    step5 = json.loads((ENV / "step5-results.json").read_text(encoding="utf-8"))
    step1 = json.loads((ENV / "step1-fixtures.json").read_text(encoding="utf-8"))
    alice = step1["users"]["alice"]
    tenant = step1["tenants"]["A"]
    login = req("POST", "/auth/login", json_body={"tenant_code": tenant["code"], "username": alice["username"], "password": alice["password"]})
    token = login["access_token"]
    fixture = step5["fixture"]
    payload = {
        "agent_id": fixture["tool_agent"]["id"],
        "query": "calculate 2+3 using the calculator tool",
        "tool_calls": [{"tool_id": fixture["tool"]["id"], "input": {"expression": "2+3"}}],
        "max_tool_rounds": 1,
    }
    request = urllib.request.Request(
        BASE + "/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    result = {"payload": payload}
    with urllib.request.urlopen(request, timeout=120) as resp:
        result["http_status"] = resp.status
        try:
            raw = resp.read().decode("utf-8", errors="replace")
            result["read_error"] = None
        except http.client.IncompleteRead as exc:
            raw = exc.partial.decode("utf-8", errors="replace")
            result["read_error"] = "IncompleteRead"
        result["raw"] = raw
        result["events"] = parse_sse(raw)
    (ENV / "step5b-repro-response.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
