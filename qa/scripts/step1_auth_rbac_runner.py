import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QA_ENV = ROOT / "qa" / "env"
QA_RECORDS = ROOT / "qa" / "records"
BASE = "http://localhost:8001/api/v1"


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def token_payload(token: str) -> dict:
    return json.loads(b64url_decode(token.split(".")[1]))


def request(method: str, path: str, *, token: str | None = None, json_body=None, headers=None, raw_body=None, content_type=None):
    url = path if path.startswith("http") else f"{BASE}{path}"
    data = None
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if raw_body is not None:
        data = raw_body
        if content_type:
            hdrs["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            text = body.decode("utf-8", errors="replace")
            parsed = parse_json(text)
            return {"status": resp.status, "body": parsed if parsed is not None else text, "headers": dict(resp.headers)}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        parsed = parse_json(text)
        return {"status": exc.code, "body": parsed if parsed is not None else text, "headers": dict(exc.headers)}


def parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def detail(resp):
    body = resp.get("body")
    if isinstance(body, dict):
        return body.get("detail", body)
    return body


def login(tenant_code: str, username: str, password: str):
    return request("POST", "/auth/login", json_body={"tenant_code": tenant_code, "username": username, "password": password})


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def run_container_script(script_name: str, env: dict[str, str]):
    cmd = ["docker", "compose", "exec", "-T"]
    for key, value in env.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend(["backend", "python", "-"])
    script = (ROOT / "qa" / "scripts" / script_name).read_text(encoding="utf-8")
    proc = subprocess.run(cmd, input=script, text=True, capture_output=True, cwd=ROOT, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{script_name} failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc.stdout.strip()


def passfail(condition: bool) -> str:
    return "PASS" if condition else "FAIL"


def has_foreign_data(resp, markers: list[str]) -> bool:
    text = json.dumps(resp.get("body"), ensure_ascii=False)
    return any(marker and marker in text for marker in markers)


def main() -> None:
    ts = str(int(time.time()))
    old_fixture = parse_json((QA_ENV / "step1-fixtures.json").read_text(encoding="utf-8")) if (QA_ENV / "step1-fixtures.json").exists() else {}
    old_a = ((old_fixture or {}).get("probe") or {}).get("created_tenant_a") or ((old_fixture or {}).get("tenants") or {}).get("A") or {}
    fixture_env = {
        "STEP1_TS": ts,
        "STEP1_ROLE": "builder",
    }
    if old_a.get("id") and old_a.get("code"):
        fixture_env["STEP1_TENANT_A_ID"] = old_a["id"]
        fixture_env["STEP1_TENANT_A_CODE"] = old_a["code"]
    fixture = json.loads(run_container_script("step1_db_fixture.py", fixture_env))
    write_json(QA_ENV / "step1-fixtures.json", fixture)

    admin_token = (QA_ENV / "admin_token.txt").read_text(encoding="utf-8").strip()
    admin_login = login("default", "admin", "Admin123!")
    alice_info = fixture["users"]["alice"]
    bob_info = fixture["users"]["bob"]
    tenant_a = fixture["tenants"]["A"]
    tenant_b = fixture["tenants"]["B"]
    alice_login = login(tenant_a["code"], alice_info["username"], alice_info["password"])
    bob_login = login(tenant_b["code"], bob_info["username"], bob_info["password"])
    if alice_login["status"] != 200 or bob_login["status"] != 200:
        raise RuntimeError(f"fixture login failed: alice={alice_login} bob={bob_login}")
    alice_token = alice_login["body"]["access_token"]
    bob_token = bob_login["body"]["access_token"]
    write_json(QA_ENV / "step1-admin-login.json", admin_login)
    write_json(QA_ENV / "step1-alice-login.json", alice_login)
    write_json(QA_ENV / "step1-bob-login.json", bob_login)
    (QA_ENV / "step1_alice_token.txt").write_text(alice_token, encoding="utf-8")
    (QA_ENV / "step1_bob_token.txt").write_text(bob_token, encoding="utf-8")

    def create_resources(label: str, token: str):
        suffix = f"{label}-{ts}"
        models = request("GET", "/models", token=token)
        mock_models = [m for m in models["body"] if m.get("name") == "mock-chat" and m.get("type") == "llm"]
        model_id = (mock_models[0] if mock_models else models["body"][0])["id"]
        kb = request(
            "POST",
            "/kbs",
            token=token,
            json_body={"name": f"QA {suffix} KB", "type": "faq", "description": f"private-{label}", "embedding_model": "mock-embedding"},
        )
        tool = request(
            "POST",
            "/tools",
            token=token,
            json_body={"name": f"QA {suffix} Tool", "type": "builtin", "schema": {"input": {"expression": "string"}}, "config": {"builtin": "calculator"}},
        )
        agent = request(
            "POST",
            "/agents",
            token=token,
            json_body={
                "name": f"QA {suffix} Agent",
                "type": "qa",
                "persona": f"private-{label}-agent",
                "model_id": model_id,
                "kb_ids": [kb["body"]["id"]],
                "tool_ids": [tool["body"]["id"]],
            },
        )
        published = request("POST", f"/agents/{agent['body']['id']}/publish", token=token)
        doc = upload_doc(token, kb["body"]["id"], f"{suffix}.txt", f"private document {label} {ts}")
        chat = request("POST", "/chat", token=token, json_body={"agent_id": agent["body"]["id"], "query": f"ping {label}", "max_tool_rounds": 0})
        conv_list = request("GET", f"/conversations?agent_id={urllib.parse.quote(agent['body']['id'])}&limit=1", token=token)
        conv = conv_list["body"][0] if conv_list["status"] == 200 and conv_list["body"] else None
        return {
            "kb": kb["body"],
            "tool": tool["body"],
            "agent": published["body"] if published["status"] == 200 else agent["body"],
            "document": doc["body"] if doc["status"] in (200, 201) else {"error": doc},
            "chat_status": chat["status"],
            "conversation": conv,
            "create_statuses": {
                "models": models["status"],
                "kb": kb["status"],
                "tool": tool["status"],
                "agent": agent["status"],
                "publish": published["status"],
                "doc": doc["status"],
                "chat": chat["status"],
                "conv_list": conv_list["status"],
            },
        }

    def upload_doc(token: str, kb_id: str, filename: str, content: str):
        boundary = f"----qa{ts}"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: text/plain\r\n\r\n"
            f"{content}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        return request("POST", f"/kbs/{kb_id}/documents", token=token, raw_body=body, content_type=f"multipart/form-data; boundary={boundary}")

    resources_a = create_resources("A", alice_token)
    resources_b = create_resources("B", bob_token)
    fixture["resources"] = {"A": slim_resources(resources_a), "B": slim_resources(resources_b)}
    write_json(QA_ENV / "step1-fixtures.json", fixture)
    write_json(QA_ENV / "step1-resource-create-details.json", {"A": resources_a, "B": resources_b})

    # Downgrade both users to member for RBAC denial checks.
    run_container_script(
        "step1_db_fixture.py",
        {
            "STEP1_ACTION": "set_member",
            "STEP1_TENANT_A_CODE": tenant_a["code"],
            "STEP1_TENANT_B_CODE": tenant_b["code"],
            "STEP1_ALICE_USERNAME": alice_info["username"],
            "STEP1_BOB_USERNAME": bob_info["username"],
        },
    )
    alice_login_member = login(tenant_a["code"], alice_info["username"], alice_info["password"])
    bob_login_member = login(tenant_b["code"], bob_info["username"], bob_info["password"])
    alice_member_token = alice_login_member["body"]["access_token"]
    bob_member_token = bob_login_member["body"]["access_token"]
    (QA_ENV / "step1_alice_member_token.txt").write_text(alice_member_token, encoding="utf-8")
    (QA_ENV / "step1_bob_member_token.txt").write_text(bob_member_token, encoding="utf-8")

    results = {"A": [], "B": [], "C": [], "D": [], "E": []}

    # A. Auth basics.
    for name, resp in [("admin", admin_login), ("alice", alice_login), ("bob", bob_login)]:
        payload = token_payload(resp["body"]["access_token"]) if resp["status"] == 200 else {}
        results["A"].append([f"A1 {name} correct login", resp["status"], payload.get("typ"), passfail(resp["status"] == 200 and payload.get("typ") == "access")])
    for name, resp in [
        ("wrong password", login(tenant_a["code"], alice_info["username"], "WrongPass123!")),
        ("missing user", login(tenant_a["code"], f"missing-{ts}", "WrongPass123!")),
        ("wrong tenant", login(f"missing-tenant-{ts}", alice_info["username"], alice_info["password"])),
    ]:
        results["A"].append([f"A2 {name}", resp["status"], detail(resp), passfail(resp["status"] == 401 and detail(resp) == "invalid_credentials")])
    refresh_ok = request("POST", "/auth/refresh", json_body={"refresh_token": alice_login["body"]["refresh_token"]})
    refresh_access = request("POST", "/auth/refresh", json_body={"refresh_token": alice_login["body"]["access_token"]})
    refresh_bad = request("POST", "/auth/refresh", json_body={"refresh_token": "not-a-jwt"})
    results["A"].extend(
        [
            ["A7 refresh token", refresh_ok["status"], token_payload(refresh_ok["body"]["access_token"]).get("typ") if refresh_ok["status"] == 200 else detail(refresh_ok), passfail(refresh_ok["status"] == 200)],
            ["A7 access as refresh", refresh_access["status"], detail(refresh_access), passfail(refresh_access["status"] == 401)],
            ["A7 garbage refresh", refresh_bad["status"], detail(refresh_bad), passfail(refresh_bad["status"] == 401)],
        ]
    )

    # B. JWT tampering.
    parts = alice_member_token.split(".")
    bad_sig = ".".join([parts[0], parts[1], b64url_encode(b"bad-signature")])
    payload = token_payload(alice_member_token)
    payload["user_id"] = bob_info["id"]
    tampered_payload = ".".join([parts[0], b64url_encode(json.dumps(payload, separators=(",", ":")).encode()), parts[2]])
    none_header = b64url_encode(json.dumps({"alg": "none", "typ": "JWT"}, separators=(",", ":")).encode())
    alg_none = ".".join([none_header, parts[1], ""])
    no_sig = ".".join([parts[0], parts[1]])
    signed_tokens = json.loads(
        run_container_script(
            "step1_make_tokens.py",
            {
                "ALICE_USER_ID": alice_info["id"],
                "ALICE_TENANT_ID": tenant_a["id"],
                "BOB_TENANT_ID": tenant_b["id"],
            },
        )
    )
    jwt_cases = [
        ("bad signature byte", bad_sig, "invalid_token"),
        ("payload changed without resign", tampered_payload, "invalid_token"),
        ("alg none", alg_none, "invalid_token"),
        ("missing signature segment", no_sig, "invalid_token"),
        ("typ non access", signed_tokens["non_access"], "invalid_token"),
        ("expired exp", signed_tokens["expired_access"], "token_expired"),
        ("tenant mismatch", signed_tokens["tenant_mismatch"], "tenant_mismatch"),
    ]
    for name, tok, expected_detail in jwt_cases:
        resp = request("GET", "/auth/me", token=tok)
        actual = detail(resp)
        expected_ok = resp["status"] == 401 and (actual == expected_detail if expected_detail in {"tenant_mismatch", "token_expired"} else actual == "invalid_token")
        results["B"].append([f"B {name}", resp["status"], actual, passfail(expected_ok)])
    no_auth = request("GET", "/auth/me")
    results["B"].append(["B no Authorization", no_auth["status"], detail(no_auth), passfail(no_auth["status"] == 401 and detail(no_auth) == "not_authenticated")])

    # C. Status checks through DB state toggles, because public admin APIs are tenant-scoped/missing.
    run_container_script(
        "step1_db_fixture.py",
        {
            "STEP1_ACTION": "alice_status",
            "STEP1_STATUS": "disabled",
            "STEP1_TENANT_A_CODE": tenant_a["code"],
            "STEP1_TENANT_B_CODE": tenant_b["code"],
            "STEP1_ALICE_USERNAME": alice_info["username"],
            "STEP1_BOB_USERNAME": bob_info["username"],
        },
    )
    alice_disabled = request("GET", "/auth/me", token=alice_member_token)
    results["C"].append(["C1 alice disabled old token", alice_disabled["status"], detail(alice_disabled), passfail(alice_disabled["status"] == 401 and detail(alice_disabled) == "inactive_identity")])
    run_container_script(
        "step1_db_fixture.py",
        {
            "STEP1_ACTION": "tenant_b_status",
            "STEP1_STATUS": "disabled",
            "STEP1_TENANT_A_CODE": tenant_a["code"],
            "STEP1_TENANT_B_CODE": tenant_b["code"],
            "STEP1_ALICE_USERNAME": alice_info["username"],
            "STEP1_BOB_USERNAME": bob_info["username"],
        },
    )
    bob_tenant_disabled = request("GET", "/auth/me", token=bob_member_token)
    results["C"].append(["C tenant B disabled old token", bob_tenant_disabled["status"], detail(bob_tenant_disabled), passfail(bob_tenant_disabled["status"] == 401 and detail(bob_tenant_disabled) == "inactive_identity")])
    run_container_script(
        "step1_db_fixture.py",
        {
            "STEP1_ACTION": "restore_active",
            "STEP1_TENANT_A_CODE": tenant_a["code"],
            "STEP1_TENANT_B_CODE": tenant_b["code"],
            "STEP1_ALICE_USERNAME": alice_info["username"],
            "STEP1_BOB_USERNAME": bob_info["username"],
        },
    )

    # D. RBAC.
    alice_me = request("GET", "/auth/me", token=alice_member_token)
    denied_tool_patch = request("PATCH", f"/tools/{fixture['resources']['A']['tool_id']}", token=alice_member_token, json_body={"name": f"Denied {ts}"})
    denied_publish = request("POST", f"/agents/{fixture['resources']['A']['agent_id']}/publish", token=alice_member_token)
    admin_tool = request("POST", "/tools", token=admin_token, json_body={"name": f"QA default admin tool {ts}", "type": "builtin", "schema": {}, "config": {"builtin": "calculator"}})
    admin_patch = request("PATCH", f"/tools/{admin_tool['body']['id']}", token=admin_token, json_body={"name": f"QA default admin tool patched {ts}"}) if admin_tool["status"] == 201 else admin_tool
    results["D"].extend(
        [
            ["D alice permissions", 200, ",".join(alice_me["body"].get("permissions", [])) if alice_me["status"] == 200 else detail(alice_me), passfail(alice_me["status"] == 200 and "agent:publish" not in alice_me["body"].get("permissions", []))],
            ["D member patch own tool", denied_tool_patch["status"], detail(denied_tool_patch), passfail(denied_tool_patch["status"] == 403)],
            ["D member publish own agent", denied_publish["status"], detail(denied_publish), passfail(denied_publish["status"] == 403)],
            ["D admin create+patch default tool", admin_patch["status"], detail(admin_patch) if admin_patch["status"] != 200 else "updated", passfail(admin_tool["status"] == 201 and admin_patch["status"] == 200)],
        ]
    )

    # E. Cross-tenant matrix. Restore builder so write attempts exercise tenant
    # isolation instead of being stopped only by RBAC.
    run_container_script(
        "step1_db_fixture.py",
        {
            "STEP1_ACTION": "set_role",
            "STEP1_ROLE_TARGET": "builder",
            "STEP1_TENANT_A_CODE": tenant_a["code"],
            "STEP1_TENANT_B_CODE": tenant_b["code"],
            "STEP1_ALICE_USERNAME": alice_info["username"],
            "STEP1_BOB_USERNAME": bob_info["username"],
        },
    )
    alice_cross_login = login(tenant_a["code"], alice_info["username"], alice_info["password"])
    bob_cross_login = login(tenant_b["code"], bob_info["username"], bob_info["password"])
    alice_cross_token = alice_cross_login["body"]["access_token"]
    bob_cross_token = bob_cross_login["body"]["access_token"]
    matrix = []
    matrix += cross_tests("alice(builder)->B", alice_cross_token, fixture["resources"]["B"], ["QA B", "private-B", tenant_b["id"]])
    matrix += cross_tests("bob(builder)->A", bob_cross_token, fixture["resources"]["A"], ["QA A", "private-A", tenant_a["id"]])
    results["E"] = matrix

    write_json(QA_ENV / "step1-results.json", results)
    markdown = render_markdown(fixture, results)
    (QA_RECORDS / "step1-auth-rbac.md").write_text(markdown, encoding="utf-8")
    print(markdown)


def slim_resources(resources: dict) -> dict:
    conv = resources.get("conversation") or {}
    doc = resources.get("document") or {}
    return {
        "kb_id": resources["kb"]["id"],
        "agent_id": resources["agent"]["id"],
        "tool_id": resources["tool"]["id"],
        "document_id": doc.get("id"),
        "conversation_id": conv.get("id"),
        "create_statuses": resources["create_statuses"],
    }


def cross_tests(direction: str, token: str, target: dict, markers: list[str]):
    rows = []

    def add(resource, operation, resp, expected_statuses=(403, 404), extra_ok=False):
        leak = has_foreign_data(resp, markers)
        ok = (resp["status"] in expected_statuses or extra_ok) and not leak
        if resp["status"] >= 500:
            ok = False
        rows.append(
            {
                "direction": direction,
                "resource": resource,
                "operation": operation,
                "status": resp["status"],
                "detail": detail(resp),
                "leaked": leak,
                "changed": False,
                "result": passfail(ok),
            }
        )

    kb = target["kb_id"]
    agent = target["agent_id"]
    tool = target["tool_id"]
    conv = target.get("conversation_id")
    doc = target.get("document_id")
    add("kb", "GET", request("GET", f"/kbs/{kb}", token=token))
    add("kb", "PATCH", request("PATCH", f"/kbs/{kb}", token=token, json_body={"description": "cross-tenant patch"}))
    add("kb", "DELETE", request("DELETE", f"/kbs/{kb}", token=token))
    add("agent", "GET", request("GET", f"/agents/{agent}", token=token))
    add("agent", "PATCH", request("PATCH", f"/agents/{agent}", token=token, json_body={"persona": "cross-tenant patch"}))
    add("agent", "DELETE", request("DELETE", f"/agents/{agent}", token=token))
    add("tool", "GET", request("GET", f"/tools/{tool}", token=token))
    add("tool", "PATCH", request("PATCH", f"/tools/{tool}", token=token, json_body={"config": {"builtin": "calculator"}}))
    add("tool", "DELETE", request("DELETE", f"/tools/{tool}", token=token))
    add("tool", "RUN", request("POST", f"/tools/{tool}/run", token=token, json_body={"input": {"expression": "1+1"}}))
    if conv:
        add("conversation", "GET", request("GET", f"/conversations/{conv}", token=token))
        add("conversation", "PATCH", request("PATCH", f"/conversations/{conv}", token=token, json_body={"title": "cross"}), extra_ok=True)
        add("conversation", "DELETE", request("DELETE", f"/conversations/{conv}", token=token), extra_ok=True)
        add("conversation_messages", "GET", request("GET", f"/conversations/{conv}/messages", token=token))
        add("chat", "POST conversation_id", request("POST", "/chat", token=token, json_body={"agent_id": agent, "conversation_id": conv, "query": "cross", "max_tool_rounds": 0}), expected_statuses=(200, 403, 404))
    if doc:
        add("document_chunks", "GET", request("GET", f"/documents/{doc}/chunks", token=token))
    add("chat", "POST agent_id", request("POST", "/chat", token=token, json_body={"agent_id": agent, "query": "cross", "max_tool_rounds": 0}), expected_statuses=(200, 403, 404))
    return rows


def render_markdown(fixture, results) -> str:
    lines = []
    lines.append("# Step 1 认证 / JWT / RBAC / 多租户隔离测试记录")
    lines.append("")
    lines.append(f"执行时间：{time.strftime('%Y-%m-%d %H:%M:%S %z')}")
    lines.append("")
    lines.append("## Fixtures")
    lines.append("")
    lines.append("口令已写入 `qa/env/step1-fixtures.json`，本记录不展开口令。")
    lines.append("")
    lines.append("| 对象 | ID / Code | 用户 | 角色流转 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| 租户 A | `{fixture['tenants']['A']['id']}` / `{fixture['tenants']['A']['code']}` | `{fixture['users']['alice']['username']}` | builder 创建资源，member 验 RBAC，builder 验跨租户写隔离 |")
    lines.append(f"| 租户 B | `{fixture['tenants']['B']['id']}` / `{fixture['tenants']['B']['code']}` | `{fixture['users']['bob']['username']}` | builder 创建资源，member 验 RBAC，builder 验跨租户写隔离 |")
    lines.append("")
    lines.append("| 租户 | KB | Agent | Tool | Conversation | Document |")
    lines.append("|---|---|---|---|---|---|")
    for key in ["A", "B"]:
        res = fixture["resources"][key]
        lines.append(f"| {key} | `{res.get('kb_id')}` | `{res.get('agent_id')}` | `{res.get('tool_id')}` | `{res.get('conversation_id')}` | `{res.get('document_id')}` |")
    lines.append("")
    for section, title in [("A", "A. 认证基础"), ("B", "B. JWT 安全"), ("C", "C. 账号/租户状态"), ("D", "D. RBAC 权限点")]:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| 用例 | 状态码 | detail/摘要 | 结论 |")
        lines.append("|---|---:|---|---:|")
        for row in results[section]:
            lines.append(f"| {row[0]} | {row[1]} | `{short(row[2])}` | {row[3]} |")
        lines.append("")
    lines.append("## E. 跨租户越权矩阵")
    lines.append("")
    lines.append("| 方向 | 资源 | 操作 | 状态码 | detail | 泄露对方数据 | 改动 | 结论 |")
    lines.append("|---|---|---|---:|---|---:|---:|---:|")
    for row in results["E"]:
        lines.append(
            f"| {row['direction']} | {row['resource']} | {row['operation']} | {row['status']} | `{short(row['detail'])}` | {row['leaked']} | {row['changed']} | {row['result']} |"
        )
    lines.append("")
    fails = collect_fails(results)
    lines.append("## 缺陷清单")
    lines.append("")
    lines.append("### P1/BLOCKER-QA：租户开通流程缺失")
    lines.append("")
    lines.append("- 复现：`POST /api/v1/tenants` 创建新租户后，用 `default/admin` 调 `POST /api/v1/users` 创建用户。")
    lines.append("- 实际：用户落在调用者 token 所属租户，无法指定新租户。")
    lines.append("- 期望：提供租户初始化管理员、指定租户建用户接口，或明确租户开通流程。")
    lines.append("- 影响：阻断纯 API 方式构造多租户 QA fixtures。")
    lines.append("")
    if fails:
        for item in fails:
            lines.append(f"### {item['severity']}：{item['name']}")
            lines.append("")
            lines.append(f"- 实际：{item['actual']}")
            lines.append(f"- 期望：{item['expected']}")
            lines.append("")
    else:
        lines.append("未发现跨租户 P0 越权数据泄露或改动成功。")
        lines.append("")
    isolation_ok = all(row["result"] == "PASS" for row in results["E"])
    auth_jwt_ok = all(row[3] == "PASS" for sec in ["A", "C", "D"] for row in results[sec])
    jwt_ok = all(row[3] == "PASS" for row in results["B"])
    lines.append("## 结论")
    lines.append("")
    lines.append(f"- 越权隔离是否守住：{'是' if isolation_ok else '否'}。")
    lines.append(f"- 认证/RBAC 基础：{'通过' if auth_jwt_ok else '存在失败'}。")
    lines.append(f"- JWT 安全：{'通过' if jwt_ok else '存在失败，见缺陷清单'}。")
    lines.append(f"- 是否可以进入 Step 2：{'可以' if isolation_ok and auth_jwt_ok else '不建议'}。")
    return "\n".join(lines) + "\n"


def short(value, max_len=180) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def collect_fails(results):
    fails = []
    for row in results["B"]:
        if row[3] == "FAIL":
            severity = "P2"
            if "expired exp" in row[0]:
                severity = "P2"
            fails.append({"severity": severity, "name": row[0], "actual": f"status={row[1]}, detail={row[2]}", "expected": "401 且 detail 符合用例预期"})
    for row in results["E"]:
        if row["result"] == "FAIL":
            severity = "P0" if row["leaked"] or row["status"] < 400 else "P1"
            fails.append({"severity": severity, "name": f"{row['direction']} {row['resource']} {row['operation']}", "actual": f"status={row['status']}, detail={row['detail']}, leaked={row['leaked']}", "expected": "404/403 且不泄露、不改动；500 视为鲁棒性缺陷"})
    return fails


if __name__ == "__main__":
    main()
