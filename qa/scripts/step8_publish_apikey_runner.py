import json
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


def ensure_member_user(tenant_id, tenant_code, ts):
    username = f"step8-member-{ts}"
    password = f"QaStep8Member{ts}!"
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
                display_name="QA Step8 Member",
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
    out = compose("exec", "-T", "backend", "python", "-", input_text=code)
    return {"command": out, "user": parse_json(out["stdout"].strip())}


def db_key_rows(app_ids, raw_keys):
    app_ids_json = json.dumps(app_ids)
    raw_keys_json = json.dumps(raw_keys)
    code = f"""
import asyncio, hashlib, json
from uuid import UUID
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import AppApiKey, PublishedApp

app_ids = [UUID(x) for x in {app_ids_json}]
raw_keys = {raw_keys_json}
raw_hashes = {{k: hashlib.sha256(k.encode("utf-8")).hexdigest() for k in raw_keys}}

async def main():
    async with SessionLocal() as db:
        result = await db.execute(select(AppApiKey).where(AppApiKey.app_id.in_(app_ids)))
        rows = []
        for key in result.scalars().all():
            rows.append({{
                "id": str(key.id),
                "tenant_id": str(key.tenant_id),
                "app_id": str(key.app_id),
                "name": key.name,
                "key_hash": key.key_hash,
                "key_prefix": key.key_prefix,
                "status": key.status,
                "raw_key_equals_hash": key.key_hash in raw_keys,
                "hash_matches_one_raw_key": key.key_hash in raw_hashes.values(),
                "prefix_matches_one_raw_key": any(k.startswith(key.key_prefix.replace("****", "")) for k in raw_keys),
            }})
        apps = []
        for app_id in app_ids:
            app = await db.get(PublishedApp, app_id)
            if app is not None:
                apps.append({{
                    "id": str(app.id),
                    "tenant_id": str(app.tenant_id),
                    "agent_id": str(app.agent_id),
                    "status": app.status,
                    "publish_type": app.publish_type,
                    "name": app.name,
                }})
        print(json.dumps({{"keys": rows, "apps": apps}}, ensure_ascii=False, indent=2))

asyncio.run(main())
"""
    out = compose("exec", "-T", "backend", "python", "-", input_text=code)
    return {"command": out, "body": parse_json(out["stdout"])}


def public_chat(app_id, api_key, query="ping from public app", **extra):
    payload = {"query": query}
    payload.update(extra)
    return req("POST", f"/public/apps/{app_id}/chat", token=api_key, json_body=payload, timeout=180)


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

    member_fixture = ensure_member_user(tenant_a["id"], tenant_a["code"], ts)
    member_login = login(tenant_a["code"], member_fixture["user"]["username"], member_fixture["user"]["password"])
    member_token = member_login["body"]["access_token"]

    ensure_agent_a_active = req("POST", f"/agents/{agent_a}/publish", token=alice_token)
    ensure_agent_b_active = req("POST", f"/agents/{agent_b}/publish", token=bob_token)

    publish_a = req("POST", "/published-apps", token=alice_token, json_body={"agent_id": agent_a, "name": f"QA Step8 A App {ts}"})
    publish_b = req("POST", "/published-apps", token=bob_token, json_body={"agent_id": agent_b, "name": f"QA Step8 B App {ts}"})
    app_a = publish_a["body"]["id"]
    app_b = publish_b["body"]["id"]

    key_a = req("POST", f"/published-apps/{app_a}/keys", token=alice_token, json_body={"name": f"QA Step8 A Key {ts}"})
    key_a_revoke = req("POST", f"/published-apps/{app_a}/keys", token=alice_token, json_body={"name": f"QA Step8 A Revoke Key {ts}"})
    key_b = req("POST", f"/published-apps/{app_b}/keys", token=bob_token, json_body={"name": f"QA Step8 B Key {ts}"})
    raw_key_a = key_a["body"]["api_key"]
    raw_key_a_revoke = key_a_revoke["body"]["api_key"]
    raw_key_b = key_b["body"]["api_key"]

    list_keys_a = req("GET", f"/published-apps/{app_a}/keys", token=alice_token)
    get_app_a = req("GET", f"/published-apps/{app_a}", token=alice_token)
    bob_get_app_a = req("GET", f"/published-apps/{app_a}", token=bob_token)
    member_publish = req("POST", "/published-apps", token=member_token, json_body={"agent_id": agent_a, "name": f"QA Step8 Member App {ts}"})

    create_draft_agent = req("POST", "/agents", token=alice_token, json_body={"name": f"QA Step8 Draft Agent {ts}", "type": "custom"})
    publish_draft_as_app = None
    if create_draft_agent["status"] == 201:
        publish_draft_as_app = req(
            "POST",
            "/published-apps",
            token=alice_token,
            json_body={"agent_id": create_draft_agent["body"]["id"], "name": f"QA Step8 Draft App {ts}"},
        )

    correct_public_chat = public_chat(app_a, raw_key_a, query="ping")
    wrong_key_chat = public_chat(app_a, "sk-forged-invalid-key", query="ping")
    no_key_chat = req("POST", f"/public/apps/{app_a}/chat", json_body={"query": "ping"})
    a_key_to_b_app = public_chat(app_b, raw_key_a, query="ping")
    b_key_to_a_app = public_chat(app_a, raw_key_b, query="ping")
    stream_rejected = public_chat(app_a, raw_key_a, query="ping", stream=True)

    disable_revoke_key = req(
        "POST",
        f"/published-apps/{app_a}/keys/{key_a_revoke['body']['id']}/status",
        token=alice_token,
        json_body={"status": "disabled"},
    )
    revoked_key_chat = public_chat(app_a, raw_key_a_revoke, query="ping")

    unpublish_b = req("POST", f"/published-apps/{app_b}/unpublish", token=bob_token)
    b_key_after_unpublish = public_chat(app_b, raw_key_b, query="ping")

    db_rows = db_key_rows([app_a, app_b], [raw_key_a, raw_key_a_revoke, raw_key_b])

    results = {
        "ts": ts,
        "git_head": git_head,
        "production_mode": production_mode,
        "fixtures": {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "alice": {"id": alice["id"], "username": alice["username"]},
            "bob": {"id": bob["id"], "username": bob["username"]},
            "member": {k: v for k, v in member_fixture["user"].items() if k != "password"},
            "agent_a": agent_a,
            "agent_b": agent_b,
            "app_a": app_a,
            "app_b": app_b,
            "key_a_id": key_a["body"]["id"],
            "key_a_revoke_id": key_a_revoke["body"]["id"],
            "key_b_id": key_b["body"]["id"],
        },
        "auth": {
            "alice_login_status": alice_login["status"],
            "bob_login_status": bob_login["status"],
            "alice_me": alice_me,
            "bob_me": bob_me,
            "member_login_status": member_login["status"],
        },
        "group1_publish_key_storage": {
            "ensure_agent_a_active": ensure_agent_a_active,
            "ensure_agent_b_active": ensure_agent_b_active,
            "publish_a": publish_a,
            "publish_b": publish_b,
            "key_a_created": key_a,
            "key_a_revoke_created": key_a_revoke,
            "key_b_created": key_b,
            "list_keys_a": list_keys_a,
            "get_app_a": get_app_a,
            "bob_get_app_a": bob_get_app_a,
            "member_publish": member_publish,
            "db_rows": db_rows,
        },
        "group2_app_api_key_auth": {
            "correct_public_chat": correct_public_chat,
            "wrong_key_chat": wrong_key_chat,
            "no_key_chat": no_key_chat,
            "a_key_to_b_app": a_key_to_b_app,
            "b_key_to_a_app": b_key_to_a_app,
            "disable_revoke_key": disable_revoke_key,
            "revoked_key_chat": revoked_key_chat,
            "b_key_after_unpublish": b_key_after_unpublish,
        },
        "group3_public_isolation": {
            "bob_get_app_a_management": bob_get_app_a,
            "publish_draft_agent": {
                "create_draft_agent": create_draft_agent,
                "publish_draft_as_app": publish_draft_as_app,
            },
            "cross_app_public": {
                "a_key_to_b_app": a_key_to_b_app,
                "b_key_to_a_app": b_key_to_a_app,
            },
        },
        "group4_public_chat": {
            "correct_public_chat": correct_public_chat,
            "stream_rejected": stream_rejected,
            "rate_limit_code_observation": "No rate limit/quota guard found in public_agents.py or api_key_auth.py; not stress tested.",
        },
    }
    (ENV / "step8-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "ts": ts,
        "production_mode": production_mode["stdout"].strip(),
        "app_a": app_a,
        "app_b": app_b,
        "key_create_has_api_key": "api_key" in key_a["body"],
        "list_keys_has_api_key": any("api_key" in item for item in list_keys_a["body"]) if isinstance(list_keys_a["body"], list) else None,
        "db_key_rows": db_rows["body"],
        "member_publish_status": member_publish["status"],
        "correct_public_chat_status": correct_public_chat["status"],
        "wrong_key_status": wrong_key_chat["status"],
        "a_key_to_b_status": a_key_to_b_app["status"],
        "b_key_to_a_status": b_key_to_a_app["status"],
        "revoked_key_status": revoked_key_chat["status"],
        "draft_publish_status": publish_draft_as_app["status"] if publish_draft_as_app else None,
        "b_key_after_unpublish_status": b_key_after_unpublish["status"],
    }
    (ENV / "step8-runner-output.md").write_text("# Step 8 Runner Output\n\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
