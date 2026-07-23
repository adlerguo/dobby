import json
import subprocess
import time
import urllib.error
import urllib.parse
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


def req(method, path, *, token=None, json_body=None, timeout=180):
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
            return {"status": resp.status, "body": parse_json(text) if parse_json(text) is not None else text}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "body": parse_json(text) if parse_json(text) is not None else text}
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
    return req("POST", "/auth/login", json_body={"tenant_code": tenant_code, "username": username, "password": password})


def ensure_no_role_user(tenant_id, tenant_code, ts):
    username = f"step9-nodash-{ts}"
    password = f"QaStep9NoDash{ts}!"
    code = f"""
import asyncio, json
from sqlalchemy import select, delete
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User, UserRole

async def main():
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.tenant_id == "{tenant_id}", User.username == "{username}"))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                tenant_id="{tenant_id}",
                username="{username}",
                password_hash=hash_password("{password}"),
                display_name="QA Step9 No Dashboard",
                email="{username}@qa.local",
                status="active",
            )
            db.add(user)
            await db.flush()
        else:
            user.password_hash = hash_password("{password}")
            user.status = "active"
            await db.flush()
        await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        await db.commit()
        print(json.dumps({{"id": str(user.id), "tenant_code": "{tenant_code}", "username": "{username}", "password": "{password}", "role": "none"}}, ensure_ascii=False))

asyncio.run(main())
"""
    out = compose("exec", "-T", "backend", "python", "-", input_text=code)
    return {"command": out, "user": parse_json(out["stdout"].strip())}


def create_failure_agent(tenant_id, user_id, ts):
    code = f"""
import asyncio, json
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import Agent, Model

async def main():
    async with SessionLocal() as db:
        model = Model(
            name="qa-step9-no-channel-{ts}",
            provider="qa",
            type="llm",
            display_name="QA Step9 No Channel {ts}",
            is_active=True,
            provider_config={{}},
            import_source="qa",
            scope_type="tenant",
        )
        db.add(model)
        await db.flush()
        agent = Agent(
            tenant_id="{tenant_id}",
            name="QA Step9 No Channel Agent {ts}",
            type="custom",
            persona="No channel failure fixture",
            config={{}},
            model_id=model.id,
            status="active",
            created_by="{user_id}",
        )
        db.add(agent)
        await db.commit()
        print(json.dumps({{"model_id": str(model.id), "model_name": model.name, "agent_id": str(agent.id)}}, ensure_ascii=False))

asyncio.run(main())
"""
    out = compose("exec", "-T", "backend", "python", "-", input_text=code)
    return {"command": out, "body": parse_json(out["stdout"].strip())}


def db_observability_snapshot(ids):
    ids_json = json.dumps(ids)
    code = f"""
import asyncio, json
from uuid import UUID
from decimal import Decimal
from sqlalchemy import select, func
from app.core.database import SessionLocal
from app.models import AuditLog, Conversation, EvalCase, EvalRun, Message, RunTrace, UsageRecord

ids = {ids_json}

def j(v):
    if isinstance(v, Decimal):
        return float(v)
    return v

async def main():
    async with SessionLocal() as db:
        conv_ids = [UUID(x) for x in ids.get("conversation_ids", []) if x]
        trace_ids = [UUID(x) for x in ids.get("trace_ids", []) if x]
        tenant_a = UUID(ids["tenant_a"])
        tenant_b = UUID(ids["tenant_b"])

        traces = []
        if conv_ids or trace_ids:
            stmt = select(RunTrace)
            if conv_ids and trace_ids:
                stmt = stmt.where((RunTrace.conversation_id.in_(conv_ids)) | (RunTrace.id.in_(trace_ids)))
            elif conv_ids:
                stmt = stmt.where(RunTrace.conversation_id.in_(conv_ids))
            else:
                stmt = stmt.where(RunTrace.id.in_(trace_ids))
            result = await db.execute(stmt.order_by(RunTrace.created_at.asc()))
            for t in result.scalars().all():
                traces.append({{
                    "id": str(t.id),
                    "tenant_id": str(t.tenant_id),
                    "conversation_id": str(t.conversation_id) if t.conversation_id else None,
                    "agent_id": str(t.agent_id) if t.agent_id else None,
                    "parent_id": str(t.parent_id) if t.parent_id else None,
                    "span_type": t.span_type,
                    "name": t.name,
                    "status": t.status,
                    "tokens": t.tokens,
                    "latency_ms": t.latency_ms,
                    "input": t.input,
                    "output": t.output,
                    "created_at": t.created_at.isoformat(),
                }})

        messages = []
        if conv_ids:
            result = await db.execute(select(Message).where(Message.conversation_id.in_(conv_ids)).order_by(Message.created_at.asc()))
            for m in result.scalars().all():
                messages.append({{
                    "id": str(m.id),
                    "tenant_id": str(m.tenant_id),
                    "conversation_id": str(m.conversation_id),
                    "role": m.role,
                    "tokens": m.tokens,
                    "citations_count": len(m.citations or []),
                    "created_at": m.created_at.isoformat(),
                    "content_prefix": (m.content or "")[:80],
                }})

        usage_rows = []
        result = await db.execute(select(UsageRecord).where(UsageRecord.tenant_id.in_([tenant_a, tenant_b])).order_by(UsageRecord.created_at.desc()).limit(50))
        for u in result.scalars().all():
            usage_rows.append({{
                "id": str(u.id),
                "tenant_id": str(u.tenant_id),
                "agent_id": str(u.agent_id) if u.agent_id else None,
                "user_id": str(u.user_id) if u.user_id else None,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "latency_ms": u.latency_ms,
                "cost": j(u.cost),
                "cache_hit": u.cache_hit,
                "created_at": u.created_at.isoformat(),
            }})

        usage_counts = {{}}
        for tenant in [tenant_a, tenant_b]:
            result = await db.execute(select(func.count(UsageRecord.id)).where(UsageRecord.tenant_id == tenant))
            usage_counts[str(tenant)] = result.scalar_one()

        audit_rows = []
        result = await db.execute(select(AuditLog).where(AuditLog.tenant_id.in_([tenant_a, tenant_b])).order_by(AuditLog.created_at.desc()).limit(80))
        for a in result.scalars().all():
            audit_rows.append({{
                "id": str(a.id),
                "tenant_id": str(a.tenant_id),
                "user_id": str(a.user_id) if a.user_id else None,
                "action": a.action,
                "resource_type": a.resource_type,
                "resource_id": str(a.resource_id) if a.resource_id else None,
                "ip": a.ip,
                "detail": a.detail,
                "created_at": a.created_at.isoformat(),
            }})

        audit_counts = {{}}
        for tenant in [tenant_a, tenant_b]:
            result = await db.execute(select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant))
            audit_counts[str(tenant)] = result.scalar_one()

        eval_rows = []
        result = await db.execute(select(EvalRun).where(EvalRun.tenant_id.in_([tenant_a, tenant_b])).order_by(EvalRun.created_at.desc()).limit(20))
        for e in result.scalars().all():
            eval_rows.append({{
                "id": str(e.id),
                "tenant_id": str(e.tenant_id),
                "agent_id": str(e.agent_id) if e.agent_id else None,
                "case_id": str(e.case_id) if e.case_id else None,
                "score": j(e.score),
                "passed": e.passed,
                "detail": e.detail,
                "created_at": e.created_at.isoformat(),
            }})

        print(json.dumps({{
            "traces": traces,
            "messages": messages,
            "usage_rows": usage_rows,
            "usage_counts": usage_counts,
            "audit_rows": audit_rows,
            "audit_counts": audit_counts,
            "eval_rows": eval_rows,
        }}, ensure_ascii=False, indent=2))

asyncio.run(main())
"""
    out = compose("exec", "-T", "backend", "python", "-", input_text=code)
    return {"command": out, "body": parse_json(out["stdout"])}


def main():
    ts = str(int(time.time()))
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    production_mode = compose("exec", "-T", "maas", "printenv", "PRODUCTION_MODE")
    step1 = json.loads((ENV / "step1-fixtures.json").read_text(encoding="utf-8"))
    tenant_a = step1["tenants"]["A"]
    tenant_b = step1["tenants"]["B"]
    alice = step1["users"]["alice"]
    bob = step1["users"]["bob"]
    agent_a = step1["resources"]["A"]["agent_id"]
    agent_b = step1["resources"]["B"]["agent_id"]

    alice_login = login(tenant_a["code"], alice["username"], alice["password"])
    bob_login = login(tenant_b["code"], bob["username"], bob["password"])
    alice_token = alice_login["body"]["access_token"]
    bob_token = bob_login["body"]["access_token"]
    alice_me = req("GET", "/auth/me", token=alice_token)
    bob_me = req("GET", "/auth/me", token=bob_token)

    no_role = ensure_no_role_user(tenant_a["id"], tenant_a["code"], ts)
    no_role_login = login(tenant_a["code"], no_role["user"]["username"], no_role["user"]["password"])
    no_role_token = no_role_login["body"]["access_token"]

    # Produce normal non-tool conversations.
    run_a1 = req("POST", f"/agents/{agent_a}/run", token=alice_token, json_body={"query": f"Step9 RAG ping A {ts}", "max_tool_rounds": 0})
    conv_a = run_a1["body"].get("conversation_id") if run_a1["status"] == 200 else None
    run_a2 = req(
        "POST",
        f"/agents/{agent_a}/run",
        token=alice_token,
        json_body={"query": f"Step9 follow up A {ts}", "conversation_id": conv_a, "max_tool_rounds": 0},
    ) if conv_a else None
    run_b1 = req("POST", f"/agents/{agent_b}/run", token=bob_token, json_body={"query": f"Step9 RAG ping B {ts}", "max_tool_rounds": 0})
    conv_b = run_b1["body"].get("conversation_id") if run_b1["status"] == 200 else None

    messages_a = req("GET", f"/conversations/{conv_a}/messages", token=alice_token) if conv_a else None
    bob_messages_a = req("GET", f"/conversations/{conv_a}/messages", token=bob_token) if conv_a else None
    trace_detail_a = req("GET", f"/traces/{run_a1['body']['trace_id']}", token=alice_token) if run_a1["status"] == 200 else None
    bob_trace_a = req("GET", f"/traces/{run_a1['body']['trace_id']}", token=bob_token) if run_a1["status"] == 200 else None

    failure_fixture = create_failure_agent(tenant_a["id"], alice["id"], ts)
    failure_run = req(
        "POST",
        f"/agents/{failure_fixture['body']['agent_id']}/run",
        token=alice_token,
        json_body={"query": f"Step9 failure no channel {ts}", "max_tool_rounds": 0},
    ) if failure_fixture["body"] else None

    # Auditable actions.
    tool_create = req(
        "POST",
        "/tools",
        token=alice_token,
        json_body={"name": f"QA Step9 Audit Tool {ts}", "type": "builtin", "schema": {}, "config": {"builtin": "echo"}},
    )
    tool_patch = req(
        "PATCH",
        f"/tools/{tool_create['body']['id']}",
        token=alice_token,
        json_body={"name": f"QA Step9 Audit Tool Renamed {ts}", "config": {"builtin": "echo", "note": "step9"}},
    ) if tool_create["status"] == 201 else None
    tool_delete = req("DELETE", f"/tools/{tool_create['body']['id']}", token=alice_token) if tool_create["status"] == 201 else None
    app_publish = req("POST", "/published-apps", token=alice_token, json_body={"agent_id": agent_a, "name": f"QA Step9 App {ts}"})

    audit_api_alice = req("GET", "/audit-logs?limit=20", token=alice_token)
    audit_api_bob = req("GET", "/audit-logs?limit=20", token=bob_token)

    dashboard_a = req("GET", "/dashboard/executive?period_days=7", token=alice_token)
    dashboard_b = req("GET", "/dashboard/executive?period_days=7", token=bob_token)
    dashboard_no_role = req("GET", "/dashboard/executive?period_days=7", token=no_role_token)

    eval_case = req(
        "POST",
        "/eval-cases",
        token=alice_token,
        json_body={"scene": f"step9-{ts}", "input": "ping", "expected": "mock response", "assert_type": "contains"},
    )
    eval_run = req(
        "POST",
        f"/agents/{agent_a}/eval",
        token=alice_token,
        json_body={"case_ids": [eval_case["body"]["id"]], "max_tool_rounds": 0, "write_passed_experiences": False},
    ) if eval_case["status"] == 201 else None
    eval_runs_list = req("GET", f"/agents/{agent_a}/eval-runs?limit=10", token=alice_token)
    bob_get_eval_case = req("GET", f"/eval-cases/{eval_case['body']['id']}", token=bob_token) if eval_case["status"] == 201 else None

    db_snapshot = db_observability_snapshot({
        "tenant_a": tenant_a["id"],
        "tenant_b": tenant_b["id"],
        "conversation_ids": [x for x in [conv_a, conv_b] if x],
        "trace_ids": [run_a1["body"].get("trace_id")] if run_a1["status"] == 200 else [],
    })

    results = {
        "ts": ts,
        "git_head": git_head,
        "production_mode": production_mode,
        "fixtures": {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "alice": {"id": alice["id"], "username": alice["username"]},
            "bob": {"id": bob["id"], "username": bob["username"]},
            "no_role": {k: v for k, v in no_role["user"].items() if k != "password"},
            "agent_a": agent_a,
            "agent_b": agent_b,
            "failure_fixture": failure_fixture["body"],
        },
        "auth": {"alice_me": alice_me, "bob_me": bob_me, "no_role_login_status": no_role_login["status"]},
        "group1_runtrace": {
            "run_a1": run_a1,
            "run_a2": run_a2,
            "run_b1": run_b1,
            "messages_a": messages_a,
            "bob_messages_a": bob_messages_a,
            "trace_detail_a": trace_detail_a,
            "bob_trace_a": bob_trace_a,
            "failure_run": failure_run,
        },
        "group2_audit": {
            "tool_create": tool_create,
            "tool_patch": tool_patch,
            "tool_delete": tool_delete,
            "app_publish": app_publish,
            "audit_api_alice": audit_api_alice,
            "audit_api_bob": audit_api_bob,
        },
        "group3_usage": {},
        "group4_dashboard": {
            "dashboard_a": dashboard_a,
            "dashboard_b": dashboard_b,
            "dashboard_no_role": dashboard_no_role,
        },
        "group5_eval": {
            "eval_case": eval_case,
            "eval_run": eval_run,
            "eval_runs_list": eval_runs_list,
            "bob_get_eval_case": bob_get_eval_case,
        },
        "db_snapshot": db_snapshot,
    }
    (ENV / "step9-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    snap = db_snapshot["body"] or {}
    trace_spans = snap.get("traces", [])
    a_trace_spans = [t for t in trace_spans if t.get("conversation_id") == conv_a]
    summary = {
        "ts": ts,
        "production_mode": production_mode["stdout"].strip(),
        "run_a1_status": run_a1["status"],
        "run_a2_status": run_a2["status"] if run_a2 else None,
        "trace_span_types_for_a": [t.get("span_type") for t in a_trace_spans],
        "trace_statuses_for_a": [t.get("status") for t in a_trace_spans],
        "messages_a_count": len(messages_a["body"]) if messages_a and isinstance(messages_a["body"], list) else None,
        "bob_messages_a_status": bob_messages_a["status"] if bob_messages_a else None,
        "trace_detail_a_status": trace_detail_a["status"] if trace_detail_a else None,
        "bob_trace_a_status": bob_trace_a["status"] if bob_trace_a else None,
        "failure_run_status": failure_run["status"] if failure_run else None,
        "audit_api_alice_status": audit_api_alice["status"],
        "audit_api_bob_status": audit_api_bob["status"],
        "audit_counts": snap.get("audit_counts"),
        "recent_audit_actions": [r.get("action") for r in snap.get("audit_rows", [])[:12]],
        "usage_counts": snap.get("usage_counts"),
        "usage_cost_values_sample": [r.get("cost") for r in snap.get("usage_rows", [])[:10]],
        "dashboard_a_status": dashboard_a["status"],
        "dashboard_b_status": dashboard_b["status"],
        "dashboard_no_role_status": dashboard_no_role["status"],
        "eval_case_status": eval_case["status"],
        "eval_run_status": eval_run["status"] if eval_run else None,
        "bob_get_eval_case_status": bob_get_eval_case["status"] if bob_get_eval_case else None,
    }
    (ENV / "step9-runner-output.md").write_text("# Step 9 Runner Output\n\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
