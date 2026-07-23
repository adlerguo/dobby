import json
import http.client
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "qa"
ENV = QA / "env"
RECORDS = QA / "records"
BASE = "http://localhost:8001/api/v1"
MAAS = "http://localhost:8100"


DOC_TEXT = """invoice approval workflow requires finance owner review and final CFO approval.

contract review must check liability, confidentiality, payment terms, delivery acceptance, and dispute resolution.

The support policy states that escalation requires a severity label and an incident owner.
"""


def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def req(method, path, *, token=None, json_body=None, raw_body=None, content_type=None, timeout=90):
    url = path if path.startswith("http") else f"{BASE}{path}"
    data = None
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if raw_body is not None:
        data = raw_body
        headers["Content-Type"] = content_type
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "body": parse_json(text) if parse_json(text) is not None else text}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "body": parse_json(text) if parse_json(text) is not None else text}


def sse_chat(token, payload, *, read_bytes=None, timeout=120):
    r = urllib.request.Request(
        f"{BASE}/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        try:
            if read_bytes is not None:
                data = resp.read(read_bytes).decode("utf-8", errors="replace")
                return {"status": resp.status, "raw": data, "events": parse_sse(data), "partial": True}
            data = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "raw": data, "events": parse_sse(data), "partial": False}
        except http.client.IncompleteRead as exc:
            data = exc.partial.decode("utf-8", errors="replace")
            return {"status": resp.status, "raw": data, "events": parse_sse(data), "partial": True, "read_error": "IncompleteRead"}


def parse_sse(raw):
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = None
        data_parts = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_parts.append(line[5:].strip())
        data_raw = "\n".join(data_parts)
        events.append({"event": event, "data": parse_json(data_raw) if parse_json(data_raw) is not None else data_raw})
    return events


def run(cmd, *, input_text=None, timeout=120):
    p = subprocess.run(cmd, cwd=ROOT, input=input_text, text=True, capture_output=True, timeout=timeout)
    return {"code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def compose_exec(service, args, *, input_text=None):
    return run(["docker", "compose", "exec", "-T", service, *args], input_text=input_text)


def psql(sql):
    res = compose_exec("postgres", ["psql", "-U", "app", "-d", "eap", "-A", "-F", "\t", "-q", "-c", sql])
    lines = [line for line in res["stdout"].splitlines() if line and not line.startswith("(")]
    if not lines:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


def login_alice():
    fx = json.loads((ENV / "step1-fixtures.json").read_text())
    alice = fx["users"]["alice"]
    tenant = fx["tenants"]["A"]
    resp = req("POST", "/auth/login", json_body={"tenant_code": tenant["code"], "username": alice["username"], "password": alice["password"]})
    if resp["status"] != 200:
        raise RuntimeError(resp)
    return resp["body"]["access_token"], fx


def upload(token, kb_id, filename, content):
    boundary = f"----qa{int(time.time()*1000)}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        f"{content}\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    return req("POST", f"/kbs/{kb_id}/documents", token=token, raw_body=body, content_type=f"multipart/form-data; boundary={boundary}")


def wait_doc(doc_id, timeout=90):
    start = time.time()
    while time.time() - start < timeout:
        rows = psql(f"select parse_status from documents where id='{doc_id}';")
        if rows and rows[0]["parse_status"] in {"done", "failed"}:
            return rows[0]["parse_status"]
        time.sleep(0.5)
    return "timeout"


def create_channel(model, tenant_id, *, base_url="mock://local", status="active", weight=1):
    return req("POST", f"{MAAS}/admin/channels", json_body={"model": model, "model_type": "llm", "provider": "mock", "tenant_id": tenant_id, "base_url": base_url, "api_key": "qa", "status": status, "weight": weight})


def patch_channel(channel_id, **values):
    return req("PATCH", f"{MAAS}/admin/channels/{channel_id}", json_body=values)


def create_fixture(token, fx, ts):
    tenant_id = fx["tenants"]["A"]["id"]
    # Create isolated LLM model/channel for this step.
    model_name = f"qa-step5-model-{ts}"
    ch = create_channel(model_name, tenant_id)
    models = req("GET", "/models", token=token)
    model_id = next(m["id"] for m in models["body"] if m["name"] == model_name and m["type"] == "llm")

    kb = req("POST", "/kbs", token=token, json_body={"name": f"QA Step5 KB {ts}", "type": "faq", "description": "qa-step5", "config": {"chunk_size": 180, "overlap": 20}, "embedding_model": "mock-embedding"})
    up = upload(token, kb["body"]["id"], "step5-doc.txt", DOC_TEXT)
    doc_status = wait_doc(up["body"]["id"])
    rag_agent = req("POST", "/agents", token=token, json_body={"name": f"QA Step5 RAG Agent {ts}", "type": "qa", "persona": "Answer using citations.", "model_id": model_id, "kb_ids": [kb["body"]["id"]], "tool_ids": [], "config": {"rag": {"match_type": "keyword", "top_k": 4}}})
    rag_pub = req("POST", f"/agents/{rag_agent['body']['id']}/publish", token=token)
    plain_agent = req("POST", "/agents", token=token, json_body={"name": f"QA Step5 Plain Agent {ts}", "type": "qa", "persona": "Plain assistant.", "model_id": model_id, "kb_ids": [], "tool_ids": []})
    plain_pub = req("POST", f"/agents/{plain_agent['body']['id']}/publish", token=token)
    tool = req("POST", "/tools", token=token, json_body={"name": f"QA Step5 Calculator {ts}", "type": "builtin", "schema": {"input": {"expression": "string"}}, "config": {"builtin": "calculator"}})
    tool_agent = req("POST", "/agents", token=token, json_body={"name": f"QA Step5 Tool Agent {ts}", "type": "qa", "persona": "Use tools when requested.", "model_id": model_id, "kb_ids": [], "tool_ids": [tool["body"]["id"]]})
    tool_pub = req("POST", f"/agents/{tool_agent['body']['id']}/publish", token=token)
    return {"model_name": model_name, "channel": ch["body"], "model_id": model_id, "kb": kb["body"], "document": up["body"], "doc_status": doc_status, "rag_agent": rag_pub["body"], "plain_agent": plain_pub["body"], "tool": tool["body"], "tool_agent": tool_pub["body"]}


def messages_api(token, conversation_id):
    return req("GET", f"/conversations/{conversation_id}/messages", token=token)


def conversation_api(token, conversation_id):
    return req("GET", f"/conversations/{conversation_id}", token=token)


def trace_tree(trace_id):
    return psql(f"select id::text,parent_id::text,span_type,name,status,tokens,latency_ms,input::text,output::text from run_traces where id='{trace_id}' or parent_id='{trace_id}' order by created_at,id;")


def conversation_db(conversation_id):
    return {
        "conversation": psql(f"select id::text,tenant_id::text,user_id::text,agent_id::text,title from conversations where id='{conversation_id}';"),
        "messages": psql(f"select id::text,role,content,tokens,citations::text from messages where conversation_id='{conversation_id}' order by created_at;"),
        "traces": psql(f"select id::text,parent_id::text,span_type,name,status,tokens,latency_ms,output::text from run_traces where conversation_id='{conversation_id}' order by created_at;"),
    }


def event_names(events):
    return [e["event"] for e in events]


def done_event(events):
    return next((e["data"] for e in events if e["event"] == "done"), None)


def main():
    token, fx = login_alice()
    ts = str(int(time.time()))
    results = {"ts": ts, "maas_production_mode": compose_exec("maas", ["printenv", "PRODUCTION_MODE"])["stdout"].strip(), "groups": {}, "defects": [], "pending_real_key": []}
    fixture = create_fixture(token, fx, ts)
    results["fixture"] = fixture

    # Group 1
    rag_stream = sse_chat(token, {"agent_id": fixture["rag_agent"]["id"], "query": "contract review payment terms", "max_tool_rounds": 0})
    plain_stream = sse_chat(token, {"agent_id": fixture["plain_agent"]["id"], "query": "hello plain", "max_tool_rounds": 0})
    results["groups"]["sse_contract"] = {
        "rag": summarize_stream(rag_stream),
        "plain": summarize_stream(plain_stream),
        "rag_full": rag_stream,
        "plain_full": plain_stream,
    }

    # Group 2
    rag_done = done_event(rag_stream["events"])
    db1 = conversation_db(rag_done["conversation_id"]) if rag_done else {}
    msgs1_api = messages_api(token, rag_done["conversation_id"]) if rag_done else {}
    follow = sse_chat(token, {"agent_id": fixture["rag_agent"]["id"], "conversation_id": rag_done["conversation_id"], "query": "continue with invoice approval workflow", "history_limit": 12, "max_tool_rounds": 0}) if rag_done else {"events": []}
    follow_done = done_event(follow["events"])
    db2 = conversation_db(rag_done["conversation_id"]) if rag_done else {}
    results["groups"]["persistence"] = {
        "first_done": rag_done,
        "db_after_first": db1,
        "messages_api": msgs1_api,
        "follow_stream": summarize_stream(follow),
        "follow_done": follow_done,
        "db_after_follow": db2,
        "trace_tree_first": trace_tree(rag_done["trace_id"]) if rag_done else [],
    }

    # Group 3 P2 and model failure.
    fake_agent = "00000000-0000-0000-0000-000000000000"
    missing_agent = sse_chat(token, {"agent_id": fake_agent, "query": "should fail"})
    fail_model = f"qa-step5-fail-{ts}"
    fail_ch = create_channel(fail_model, fx["tenants"]["A"]["id"], base_url="mock://local")
    models = req("GET", "/models", token=token)
    fail_model_id = next(m["id"] for m in models["body"] if m["name"] == fail_model and m["type"] == "llm")
    fail_agent = req("POST", "/agents", token=token, json_body={"name": f"QA Step5 Fail Agent {ts}", "type": "qa", "persona": "fail", "model_id": fail_model_id, "kb_ids": [], "tool_ids": []})
    fail_pub = req("POST", f"/agents/{fail_agent['body']['id']}/publish", token=token)
    patch_channel(fail_ch["body"]["id"], status="disabled")
    model_fail = sse_chat(token, {"agent_id": fail_pub["body"]["id"], "query": "model should fail"})
    # Restore for hygiene.
    patch_channel(fail_ch["body"]["id"], status="active", health="ok")
    model_fail_conv = find_latest_conversation(fail_pub["body"]["id"])
    model_fail_db = conversation_db(model_fail_conv) if model_fail_conv else {}
    results["groups"]["errors"] = {
        "missing_agent": summarize_stream(missing_agent),
        "missing_agent_full": missing_agent,
        "model_fail": summarize_stream(model_fail),
        "model_fail_full": model_fail,
        "model_fail_conversation_id": model_fail_conv,
        "model_fail_db": model_fail_db,
    }

    # Group 4 tool loop. Use explicit tool_calls so demo LLM does not need to infer.
    tool_stream = sse_chat(
        token,
        {
            "agent_id": fixture["tool_agent"]["id"],
            "query": "calculate 2+3 using the calculator tool",
            "tool_calls": [{"tool_id": fixture["tool"]["id"], "input": {"expression": "2+3"}}],
            "max_tool_rounds": 1,
        },
    )
    tool_done = done_event(tool_stream["events"])
    results["groups"]["tool_loop"] = {
        "stream": summarize_stream(tool_stream),
        "full": tool_stream,
        "done": tool_done,
        "db": conversation_db(tool_done["conversation_id"]) if tool_done else {},
        "raw_contains_tool_json": "tool_calls" in tool_stream["raw"] or "tool_id" in tool_stream["raw"],
    }

    # Group 5 boundaries.
    empty_query = req("POST", "/chat", token=token, json_body={"agent_id": fixture["plain_agent"]["id"], "query": ""})
    long_query = "very long query " * 900
    long_stream = sse_chat(token, {"agent_id": fixture["rag_agent"]["id"], "query": long_query, "max_tokens": 256, "history_limit": 50, "max_tool_rounds": 0})
    long_done = done_event(long_stream["events"])
    partial = sse_chat(token, {"agent_id": fixture["plain_agent"]["id"], "query": "partial disconnect observation", "max_tool_rounds": 0}, read_bytes=80)
    time.sleep(1)
    latest_plain = find_latest_conversation(fixture["plain_agent"]["id"])
    results["groups"]["boundaries"] = {
        "empty_query": empty_query,
        "long_stream": summarize_stream(long_stream),
        "long_db": conversation_db(long_done["conversation_id"]) if long_done else {},
        "partial_disconnect": partial,
        "latest_plain_after_partial": latest_plain,
        "latest_plain_db": conversation_db(latest_plain) if latest_plain else {},
    }
    results["pending_real_key"] = [
        "真实 token 级流式首字延迟与边生成边显示：demo 走 mock_chat_stream，不覆盖 proxy_openai_stream 的真实上游行为。",
        "R4 真实上游 hang/timeout=None 是否永久挂起：需慢速或挂起上游/toxiproxy。",
        "真实 usage token 数准确性：demo mock usage 只能验证字段链路。",
    ]
    assess(results)
    (ENV / "step5-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md = render(results)
    (RECORDS / "step5-chat-stream.md").write_text(md, encoding="utf-8")
    print(md)


def summarize_stream(stream):
    events = stream.get("events", [])
    done = done_event(events)
    return {
        "http_status": stream.get("status"),
        "event_sequence": event_names(events),
        "event_count": len(events),
        "citation_count": sum(1 for e in events if e["event"] == "citation"),
        "delta_count": sum(1 for e in events if e["event"] == "delta"),
        "has_done": done is not None,
        "done": done,
        "errors": [e["data"] for e in events if e["event"] == "error"],
        "raw_excerpt": stream.get("raw", "")[:500],
    }


def find_latest_conversation(agent_id):
    rows = psql(f"select id::text from conversations where agent_id='{agent_id}' order by created_at desc limit 1;")
    return rows[0]["id"] if rows else None


def assess(results):
    sse = results["groups"]["sse_contract"]
    rag_seq = sse["rag"]["event_sequence"]
    if not (rag_seq and rag_seq[-1] == "done" and "delta" in rag_seq and sse["rag"]["citation_count"] >= 1):
        results["defects"].append({"severity": "P1", "group": "sse", "name": "RAG SSE sequence invalid", "evidence": sse["rag"]})
    plain_seq = sse["plain"]["event_sequence"]
    if not (plain_seq and plain_seq[-1] == "done" and plain_seq[0] == "delta" and "citation" not in plain_seq):
        results["defects"].append({"severity": "P1", "group": "sse", "name": "plain SSE sequence invalid", "evidence": sse["plain"]})
    pers = results["groups"]["persistence"]
    msgs = pers["db_after_follow"].get("messages", [])
    if len(msgs) < 4:
        results["defects"].append({"severity": "P1", "group": "persistence", "name": "conversation continuation did not accumulate messages", "evidence": pers})
    traces = pers.get("trace_tree_first", [])
    if not any(t["span_type"] == "agent" and t["status"] == "ok" for t in traces) or not any(t["span_type"] == "model" and t["status"] == "ok" for t in traces):
        results["defects"].append({"severity": "P1", "group": "persistence", "name": "trace tree missing ok agent/model span", "evidence": traces})
    errors = results["groups"]["errors"]
    if not (errors["missing_agent"]["http_status"] == 200 and errors["missing_agent"]["errors"] and errors["missing_agent"]["errors"][0].get("detail") == "agent_not_found"):
        results["defects"].append({"severity": "P2", "group": "P2", "name": "missing agent did not return 200 SSE error", "evidence": errors["missing_agent"]})
    mf = errors["model_fail_db"]
    mf_msgs = mf.get("messages", [])
    mf_traces = mf.get("traces", [])
    if not (errors["model_fail"]["errors"] and any(t["status"] == "failed" for t in mf_traces) and len([m for m in mf_msgs if m["role"] == "user"]) == 1 and not any(m["role"] == "assistant" for m in mf_msgs)):
        results["defects"].append({"severity": "P1", "group": "R6", "name": "model failure trace/message convergence invalid", "evidence": errors})
    tool = results["groups"]["tool_loop"]
    if tool["raw_contains_tool_json"]:
        results["defects"].append({"severity": "P2", "group": "R5", "name": "tool loop exposed raw tool JSON", "evidence": tool["stream"]})
    if not (tool["done"] and tool["done"].get("tool_results")):
        results["defects"].append({"severity": "P1", "group": "tool_loop", "name": "tool result missing from done event", "evidence": tool})


def short(obj, max_len=240):
    text = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def render(results):
    lines = ["# Step 5 对话流式 SSE 测试记录", "", f"执行时间：{time.strftime('%Y-%m-%d %H:%M:%S %z')}", f"MaaS PRODUCTION_MODE：`{results['maas_production_mode']}`", ""]
    sse = results["groups"]["sse_contract"]
    lines += ["## 第 1 组：SSE 事件契约", "", "| 场景 | HTTP | 事件序列 | citation | delta | done | 结论 |", "|---|---:|---|---:|---:|---:|---:|", f"| 带 KB agent | {sse['rag']['http_status']} | `{sse['rag']['event_sequence']}` | {sse['rag']['citation_count']} | {sse['rag']['delta_count']} | {sse['rag']['has_done']} | {'PASS' if sse['rag']['has_done'] and sse['rag']['citation_count'] else 'FAIL'} |", f"| 纯 LLM agent | {sse['plain']['http_status']} | `{sse['plain']['event_sequence']}` | {sse['plain']['citation_count']} | {sse['plain']['delta_count']} | {sse['plain']['has_done']} | {'PASS' if sse['plain']['has_done'] and not sse['plain']['citation_count'] else 'FAIL'} |", ""]
    pers = results["groups"]["persistence"]
    lines += ["## 第 2 组：消息与会话落库", "", f"- 第一轮 done：`{short(pers['first_done'])}`", f"- 续聊 done：`{short(pers['follow_done'])}`", f"- 续聊后 messages 行数：{len(pers['db_after_follow'].get('messages', []))}", f"- 第一轮 trace tree：`{short(pers['trace_tree_first'])}`", ""]
    err = results["groups"]["errors"]
    lines += ["## 第 3 组：错误处理 / R6 / P2", "", f"- 不存在 agent：HTTP {err['missing_agent']['http_status']}，events=`{err['missing_agent']['event_sequence']}`，errors=`{err['missing_agent']['errors']}`", f"- 模型失败：events=`{err['model_fail']['event_sequence']}`，errors=`{err['model_fail']['errors']}`", f"- 模型失败 DB：`{short(err['model_fail_db'])}`", ""]
    tool = results["groups"]["tool_loop"]
    lines += ["## 第 4 组：工具循环 / R5", "", f"- 事件序列：`{tool['stream']['event_sequence']}`", f"- done.tool_results：`{short(tool['done'].get('tool_results') if tool['done'] else None)}`", f"- SSE raw 是否含 tool JSON：{tool['raw_contains_tool_json']}", f"- DB/trace：`{short(tool['db'])}`", ""]
    b = results["groups"]["boundaries"]
    lines += ["## 第 5 组：边界", "", f"- 空 query：HTTP {b['empty_query']['status']}，body=`{short(b['empty_query']['body'])}`", f"- 超长 query：events=`{b['long_stream']['event_sequence']}`，DB=`{short(b['long_db'])}`", f"- 中途断开观察：partial=`{short(b['partial_disconnect'])}`，latest_db=`{short(b['latest_plain_db'])}`", ""]
    lines += ["## 待真 key 补测", ""]
    for item in results["pending_real_key"]:
        lines.append(f"- {item}")
    lines += ["", "## 缺陷记录", ""]
    if results["defects"]:
        for d in results["defects"]:
            lines.append(f"- {d['severity']} `{d['group']}` {d['name']}: `{short(d['evidence'])}`")
    else:
        lines.append("- 未发现新增阻断性缺陷。P2 复验为当前行为，R5/R6 本轮未复现。")
    has_p1 = any(d["severity"] == "P1" for d in results["defects"])
    lines += ["", "## 结论", "", f"- 流式骨架是否可靠：{'是，demo 骨架通过' if not has_p1 else '存在 P1 缺陷'}。", f"- P2 复验：HTTP 200 包 SSE error 行为存在。", f"- R5：{'成立' if any(d['group']=='R5' for d in results['defects']) else '本轮显式工具调用未暴露原始 tool JSON'}。", f"- R6：{'存在失败' if any(d['group']=='R6' for d in results['defects']) else '模型失败时 trace/message 状态收敛'}。", f"- 是否可以进入 Step 6：{'可以' if not has_p1 else '不建议'}。"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
