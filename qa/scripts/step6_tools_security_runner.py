import json
import os
import subprocess
import time
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
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            parsed = parse_json(text)
            return {"status": resp.status, "body": parsed if parsed is not None else text}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        parsed = parse_json(text)
        return {"status": exc.code, "body": parsed if parsed is not None else text}
    except Exception as exc:
        return {"status": "client_error", "body": {"error": type(exc).__name__, "detail": str(exc)}}


def compose(*args, input_text=None, timeout=120):
    proc = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def login(tenant_code, username, password):
    return req(
        "POST",
        "/auth/login",
        json_body={"tenant_code": tenant_code, "username": username, "password": password},
    )


def create_tool(token, name, tool_type, config=None, schema=None):
    return req(
        "POST",
        "/tools",
        token=token,
        json_body={
            "name": name,
            "type": tool_type,
            "schema": schema or {},
            "config": config or {},
        },
    )


def run_tool(token, tool_id, payload, timeout=120):
    return req("POST", f"/tools/{tool_id}/run", token=token, json_body={"input": payload}, timeout=timeout)


def ensure_member_user(tenant_id, tenant_code, ts):
    username = f"step6-member-{ts}"
    password = f"QaStep6Member{ts}!"
    code = f"""
import asyncio, json
from sqlalchemy import select, delete
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User, Role, UserRole

async def main():
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.tenant_id == "{tenant_id}", User.username == "{username}"))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                tenant_id="{tenant_id}",
                username="{username}",
                password_hash=hash_password("{password}"),
                display_name="QA Step6 Member",
                email="{username}@qa.local",
                status="active",
            )
            db.add(user)
            await db.flush()
        else:
            user.password_hash = hash_password("{password}")
            user.status = "active"
            await db.flush()
        result = await db.execute(select(Role).where(Role.tenant_id == "{tenant_id}", Role.code == "member"))
        role = result.scalar_one()
        await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        db.add(UserRole(user_id=user.id, role_id=role.id))
        await db.commit()
        print(json.dumps({{"id": str(user.id), "tenant_code": "{tenant_code}", "username": "{username}", "password": "{password}", "role": "member"}}, ensure_ascii=False))

asyncio.run(main())
"""
    result = compose("exec", "-T", "backend", "python", "-", input_text=code)
    parsed = parse_json(result["stdout"].strip())
    return {"command": result, "user": parsed}


def summarize_body(value, limit=1600):
    text = json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value
    if len(text) <= limit:
        return value
    return text[:limit] + "\n...[truncated]"


def main():
    ts = str(int(time.time()))
    step1 = json.loads((ENV / "step1-fixtures.json").read_text(encoding="utf-8"))
    tenant = step1["tenants"]["A"]
    alice = step1["users"]["alice"]

    production_mode = compose("exec", "-T", "maas", "printenv", "PRODUCTION_MODE")
    alice_login = login(tenant["code"], alice["username"], alice["password"])
    alice_token = alice_login["body"]["access_token"]
    alice_me = req("GET", "/auth/me", token=alice_token)

    member_fixture = ensure_member_user(tenant["id"], tenant["code"], ts)
    member_login = login(tenant["code"], member_fixture["user"]["username"], member_fixture["user"]["password"])
    member_token = member_login["body"]["access_token"]
    member_me = req("GET", "/auth/me", token=member_token)

    code_tool = create_tool(alice_token, f"QA Step6 Code {ts}", "code")
    http_tool = create_tool(alice_token, f"QA Step6 HTTP {ts}", "http")
    nl2_tool = create_tool(
        alice_token,
        f"QA Step6 NL2Data {ts}",
        "builtin",
        config={"builtin": "nl2data", "db_path": "demo_data/12345_workorders_demo.sqlite", "allowed_tables": ["work_orders"]},
    )
    echo_tool = create_tool(alice_token, f"QA Step6 Echo {ts}", "builtin", config={"builtin": "echo"})
    calc_tool = create_tool(alice_token, f"QA Step6 Calc {ts}", "builtin", config={"builtin": "calculator"})

    code_run = run_tool(
        alice_token,
        code_tool["body"]["id"],
        {
            "code": "import os\nprint('QA_R1_DIRECT_CODE_OK')\nprint('ENV_NAMES=' + ','.join(sorted(os.environ.keys())[:8]))",
            "timeout_seconds": 5,
        },
    )

    http_targets = [
        "http://minio:9000",
        "http://minio:9001",
        "http://maas:8100/admin/channels",
        "http://postgres:5432",
        "http://sandbox:8200/healthz",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8001/healthz",
    ]
    http_runs = {}
    for target in http_targets:
        timeout = 1 if "169.254.169.254" in target else 2
        http_runs[target] = run_tool(
            alice_token,
            http_tool["body"]["id"],
            {"url": target, "method": "GET", "timeout_seconds": timeout},
            timeout=10,
        )

    sql_cases = {
        "case_mixed_select": "SeLeCt COUNT(*) AS c FROM work_orders",
        "case_comment_between_select": "select/**/count(*) from work_orders",
        "case_multiple_statements": "SELECT COUNT(*) AS c FROM work_orders; SELECT 1",
        "case_cte_allowed_table": "WITH x AS (SELECT COUNT(*) AS c FROM work_orders) SELECT * FROM x",
        "case_sqlite_master_direct": "SELECT name FROM sqlite_master",
        "case_sqlite_master_subquery": "SELECT task_id FROM work_orders WHERE task_id IN (SELECT name FROM sqlite_master)",
        "case_join_disallowed": "SELECT w.task_id FROM work_orders w JOIN sqlite_master s ON 1=0",
        "case_pragma": "PRAGMA table_info(work_orders)",
        "case_line_comment": "SELECT COUNT(*) AS c FROM work_orders WHERE 1=1 -- harmless comment",
        "case_keyword_literal_false_positive": "SELECT ' insert ' AS marker FROM work_orders LIMIT 1",
    }
    sql_runs = {
        name: run_tool(
            alice_token,
            nl2_tool["body"]["id"],
            {"question": name, "sql": sql},
        )
        for name, sql in sql_cases.items()
    }

    crud = {
        "list": req("GET", "/tools", token=alice_token),
        "get_code": req("GET", f"/tools/{code_tool['body']['id']}", token=alice_token),
        "patch_echo": req(
            "PATCH",
            f"/tools/{echo_tool['body']['id']}",
            token=alice_token,
            json_body={"name": f"QA Step6 Echo Renamed {ts}", "config": {"builtin": "echo", "note": "patched"}},
        ),
        "delete_calc": req("DELETE", f"/tools/{calc_tool['body']['id']}", token=alice_token),
        "run_disabled_calc": run_tool(alice_token, calc_tool["body"]["id"], {"expression": "2+3"}),
        "member_create_tool": create_tool(member_token, f"QA Step6 Member Forbidden {ts}", "builtin", config={"builtin": "echo"}),
    }

    p0_confirm = None
    try:
        step5 = json.loads((ENV / "step5-results.json").read_text(encoding="utf-8"))
        fixture = step5["fixture"]
        p0_confirm = req(
            "POST",
            f"/agents/{fixture['tool_agent']['id']}/run",
            token=alice_token,
            json_body={
                "query": "calculate 2+3 using calculator",
                "tool_calls": [{"tool_id": fixture["tool"]["id"], "input": {"expression": "2+3"}}],
                "max_tool_rounds": 1,
            },
        )
    except Exception as exc:
        p0_confirm = {"status": "skipped", "body": {"error": type(exc).__name__, "detail": str(exc)}}

    backend_logs = compose("logs", "--tail=160", "backend")

    out = {
        "ts": ts,
        "production_mode": production_mode,
        "fixtures": {
            "tenant": tenant,
            "alice": {"id": alice["id"], "username": alice["username"], "role": alice["role"]},
            "member": {k: v for k, v in member_fixture["user"].items() if k != "password"},
            "tools": {
                "code": code_tool["body"],
                "http": http_tool["body"],
                "nl2data": nl2_tool["body"],
                "echo": echo_tool["body"],
                "calculator_disabled": calc_tool["body"],
            },
        },
        "auth": {
            "alice_login_status": alice_login["status"],
            "alice_me": alice_me,
            "member_login_status": member_login["status"],
            "member_me": member_me,
        },
        "r1_code_direct_run": code_run,
        "r2_http_runs": http_runs,
        "r7_sql_cases": sql_runs,
        "crud_permissions": crud,
        "p0_agent_orchestration_confirm": p0_confirm,
        "backend_logs_tail": backend_logs,
    }
    (ENV / "step6-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown = []
    markdown.append(f"# Step 6 Runner Output\n\n- ts: `{ts}`")
    markdown.append(f"- PRODUCTION_MODE: `{production_mode['stdout'].strip()}`")
    markdown.append(f"- Alice permissions: `{alice_me['body'].get('permissions')}`")
    markdown.append(f"- Member permissions: `{member_me['body'].get('permissions')}`")
    markdown.append("\n## R1 Code Direct Run\n")
    markdown.append(f"- HTTP: `{code_run['status']}`")
    markdown.append("```json\n" + json.dumps(summarize_body(code_run["body"]), ensure_ascii=False, indent=2) + "\n```")
    markdown.append("\n## R2 HTTP Targets\n")
    for target, result in http_runs.items():
        body = result["body"]
        output = body.get("output") if isinstance(body, dict) else body
        markdown.append(f"- `{target}` -> API `{result['status']}`, output `{summarize_body(output, 500)}`")
    markdown.append("\n## R7 SQL Cases\n")
    for name, result in sql_runs.items():
        output = result["body"].get("output") if isinstance(result["body"], dict) else result["body"]
        markdown.append(f"- `{name}` -> API `{result['status']}`, output `{summarize_body(output, 700)}`")
    markdown.append("\n## CRUD / Permission\n")
    markdown.append("```json\n" + json.dumps({k: summarize_body(v, 800) for k, v in crud.items()}, ensure_ascii=False, indent=2) + "\n```")
    markdown.append("\n## Agent Orchestration P0 Confirm\n")
    markdown.append("```json\n" + json.dumps(summarize_body(p0_confirm, 1600), ensure_ascii=False, indent=2) + "\n```")
    (ENV / "step6-runner-output.md").write_text("\n".join(markdown), encoding="utf-8")
    print("\n".join(markdown))


if __name__ == "__main__":
    main()
