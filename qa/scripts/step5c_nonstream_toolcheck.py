import json
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "qa" / "env"
BASE = "http://localhost:8001/api/v1"


def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def req(method, path, *, token=None, json_body=None, timeout=120):
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "body": parse_json(text) if parse_json(text) is not None else text}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "body": parse_json(text) if parse_json(text) is not None else text}


def main():
    step1 = json.loads((ENV / "step1-fixtures.json").read_text(encoding="utf-8"))
    step5 = json.loads((ENV / "step5-results.json").read_text(encoding="utf-8"))
    alice = step1["users"]["alice"]
    tenant = step1["tenants"]["A"]
    login = req("POST", "/auth/login", json_body={"tenant_code": tenant["code"], "username": alice["username"], "password": alice["password"]})
    token = login["body"]["access_token"]
    fixture = step5["fixture"]

    nonstream_tool = req(
        "POST",
        f"/agents/{fixture['tool_agent']['id']}/run",
        token=token,
        json_body={
            "query": "calculate 2+3 using calculator",
            "tool_calls": [{"tool_id": fixture["tool"]["id"], "input": {"expression": "2+3"}}],
            "max_tool_rounds": 1,
        },
    )
    direct_tool = req(
        "POST",
        f"/tools/{fixture['tool']['id']}/run",
        token=token,
        json_body={"input": {"expression": "2+3"}},
    )

    # Find a seeded nl2data agent if present in this tenant.
    agents = req("GET", "/agents", token=token)
    nl2data = next((agent for agent in agents["body"] if agent.get("type") == "nl2data" and agent.get("status") == "active"), None)
    nl2data_run = None
    if nl2data:
        nl2data_run = req(
            "POST",
            f"/agents/{nl2data['id']}/run",
            token=token,
            json_body={"query": "按街镇统计工单量排名前5", "max_tool_rounds": 1},
        )

    out = {
        "tool_agent_id": fixture["tool_agent"]["id"],
        "tool_id": fixture["tool"]["id"],
        "nonstream_tool_run": nonstream_tool,
        "direct_tool_run": direct_tool,
        "nl2data_agent": nl2data,
        "nl2data_run": nl2data_run,
    }
    (ENV / "step5c-nonstream-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
