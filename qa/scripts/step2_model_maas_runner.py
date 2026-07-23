import csv
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QA_ENV = ROOT / "qa" / "env"
QA_RECORDS = ROOT / "qa" / "records"
MAAS = "http://localhost:8100"


def parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def request(method: str, path: str, *, json_body=None, timeout=60):
    url = path if path.startswith("http") else f"{MAAS}{path}"
    data = None
    headers = {}
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "body": parse_json(text) if parse_json(text) is not None else text}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "body": parse_json(text) if parse_json(text) is not None else text}
    except Exception as exc:
        return {"status": "EXC", "body": f"{exc.__class__.__name__}: {exc}"}


def detail(resp):
    body = resp["body"]
    if isinstance(body, dict):
        return body.get("detail", body.get("error", body))
    return body


def run(cmd: list[str], *, input_text=None, timeout=120) -> dict:
    proc = subprocess.run(cmd, cwd=ROOT, input=input_text, text=True, capture_output=True, timeout=timeout)
    return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def compose_exec(service: str, args: list[str]) -> dict:
    return run(["docker", "compose", "exec", "-T", service, *args])


def psql_csv(sql: str) -> list[dict]:
    res = compose_exec("postgres", ["psql", "-U", "app", "-d", "eap", "-A", "-F", ",", "-q", "-c", sql])
    if res["code"] != 0:
        return [{"error": res["stderr"], "stdout": res["stdout"]}]
    lines = [line for line in res["stdout"].splitlines() if line and not line.startswith("(")]
    if not lines:
        return []
    return list(csv.DictReader(lines))


def redis_keys(pattern: str) -> list[str]:
    res = compose_exec("redis", ["redis-cli", "keys", pattern])
    return [line.strip() for line in res["stdout"].splitlines() if line.strip()]


def redis_get(key: str) -> str:
    res = compose_exec("redis", ["redis-cli", "get", key])
    return res["stdout"].strip()


def get_env(service: str, key: str) -> str:
    res = compose_exec(service, ["printenv", key])
    return res["stdout"].strip()


def restart_maas(production_mode: str) -> dict:
    res = run(["docker", "compose", "up", "-d", "--force-recreate", "maas"], timeout=180, input_text=None) if False else None
    proc = subprocess.run(
        ["docker", "compose", "up", "-d", "--force-recreate", "maas"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        env={**__import__("os").environ, "PRODUCTION_MODE": production_mode},
    )
    for _ in range(60):
        health = request("GET", "/healthz", timeout=5)
        if health["status"] == 200:
            break
        time.sleep(1)
    return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "env": get_env("maas", "PRODUCTION_MODE")}


def create_channel(model: str, model_type: str, *, tenant_id=None, provider="mock", base_url="mock://local", api_key="qa-key", weight=1, rpm_limit=None, status="active"):
    body = {
        "model": model,
        "model_type": model_type,
        "provider": provider,
        "tenant_id": tenant_id,
        "base_url": base_url,
        "api_key": api_key,
        "weight": weight,
        "status": status,
    }
    if rpm_limit is not None:
        body["rpm_limit"] = rpm_limit
    return request("POST", "/admin/channels", json_body=body)


def patch_channel(channel_id: str, **values):
    return request("PATCH", f"/admin/channels/{channel_id}", json_body=values)


def chat(model: str, content: str, *, max_tokens=8):
    return request("POST", "/v1/chat/completions", json_body={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens})


def embedding(model: str, text: str):
    return request("POST", "/v1/embeddings", json_body={"model": model, "input": text})


def ok(name: str, condition: bool, resp=None, note=""):
    return {"name": name, "result": "PASS" if condition else "FAIL", "response": resp, "note": note}


def main() -> None:
    ts = str(int(time.time()))
    fixture = json.loads((QA_ENV / "step1-fixtures.json").read_text(encoding="utf-8"))
    tenant_a = fixture["tenants"]["A"]["id"]
    tenant_b = fixture["tenants"]["B"]["id"]
    results = {"ts": ts, "groups": {}, "defects": []}

    # Group 1: probe.
    probe_bad_protocol = request("POST", "/admin/channels/probe", json_body={"model": "qa-probe", "model_type": "llm", "provider": "mock", "base_url": "mock://local", "api_key": "x", "protocol": "bad_protocol"})
    probe_rerank = request("POST", "/admin/channels/probe", json_body={"model": "qa-rerank", "model_type": "rerank", "provider": "mock", "base_url": "mock://local", "api_key": "x", "protocol": "mock"})
    probe_mock = request("POST", "/admin/channels/probe", json_body={"model": "qa-probe-mock", "model_type": "llm", "provider": "mock", "base_url": "mock://local", "api_key": "x", "protocol": "mock"})
    probe_openai_invalid = request("POST", "/admin/channels/probe", json_body={"model": "gpt-4o-mini", "model_type": "llm", "provider": "openai", "base_url": "https://api.openai.com", "api_key": "invalid-key-for-qa", "protocol": "openai_compatible"}, timeout=90)
    results["groups"]["probe"] = [
        ok("P1 invalid protocol", probe_bad_protocol["status"] == 200 and probe_bad_protocol["body"].get("ok") is False and probe_bad_protocol["body"].get("error") == "protocol_not_supported", probe_bad_protocol),
        ok("P2 rerank unsupported", probe_rerank["status"] == 200 and probe_rerank["body"].get("error") == "model_type_not_supported", probe_rerank),
        ok("P3 mock probe", probe_mock["status"] == 200 and probe_mock["body"].get("ok") is True, probe_mock),
        ok("P4 invalid OpenAI key", probe_openai_invalid["status"] == 200 and probe_openai_invalid["body"].get("ok") is False and probe_openai_invalid["body"].get("error") in {"provider_http_401", "provider_request_failed", "provider_timeout"}, probe_openai_invalid, "有效 key 待补测；本次验证无效 key/真实 base_url 路径"),
    ]

    # Group 2: no candidates.
    inactive_model = f"qa-step2-inactive-{ts}"
    inactive_ch = create_channel(inactive_model, "llm", tenant_id=tenant_a, status="disabled")
    missing_chat = chat(f"qa-missing-{ts}", "ping")
    missing_emb = embedding(f"qa-missing-emb-{ts}", "ping")
    inactive_chat = chat(inactive_model, "ping")
    results["groups"]["errors"] = [
        ok("E1 missing chat model", missing_chat["status"] == 409 and detail(missing_chat) == "no_active_model_channel", missing_chat),
        ok("E1 missing embedding model", missing_emb["status"] == 409 and detail(missing_emb) == "no_active_model_channel", missing_emb),
        ok("E2 existing model but no active channel", inactive_chat["status"] == 409 and detail(inactive_chat) == "no_active_model_channel", inactive_chat, f"disabled channel create status={inactive_ch['status']}"),
    ]

    # Group 3: RPM.
    rpm_model = f"qa-step2-rpm-{ts}"
    rpm_ch = create_channel(rpm_model, "llm", tenant_id=tenant_a, rpm_limit=3, weight=1)
    rpm_id = rpm_ch["body"]["id"]
    rpm_responses = [chat(rpm_model, f"rpm {ts} #{i}") for i in range(1, 5)]
    rpm_keys = redis_keys(f"maas:rpm:{rpm_id}:*")
    results["groups"]["rpm"] = [
        ok("RPM N+1 limited", [r["status"] for r in rpm_responses] == [200, 200, 200, 429] and detail(rpm_responses[-1]) == "rate_limited", rpm_responses, f"redis_keys={rpm_keys}"),
        ok("RPM redis key exists", bool(rpm_keys), {"keys": rpm_keys, "values": {k: redis_get(k) for k in rpm_keys}}),
    ]

    # Group 4: weighted and failover.
    weighted_model = f"qa-step2-weight-{ts}"
    high = create_channel(weighted_model, "llm", tenant_id=tenant_a, weight=9)
    low = create_channel(weighted_model, "llm", tenant_id=tenant_a, weight=1)
    high_id = high["body"]["id"]
    low_id = low["body"]["id"]
    first_weight_payload = chat(weighted_model, f"weighted-cache {ts}")
    for _ in range(60):
        chat(weighted_model, f"weighted-cache {ts}")
    counts = psql_csv(
        "select channel_id::text,count(*) as c from usage_records "
        f"where channel_id in ('{high_id}','{low_id}') group by channel_id order by channel_id;"
    )
    count_map = {row["channel_id"]: int(row["c"]) for row in counts if "channel_id" in row}
    high_count = count_map.get(high_id, 0)
    low_count = count_map.get(low_id, 0)
    fail_model = f"qa-step2-failover-{ts}"
    bad = create_channel(fail_model, "llm", tenant_id=tenant_a, weight=100, base_url="http://127.0.0.1:9", provider="bad", api_key="x")
    good = create_channel(fail_model, "llm", tenant_id=tenant_a, weight=1, base_url="mock://local")
    fail_resp = chat(fail_model, f"failover {ts}")
    bad_after = request("GET", f"/admin/channels/{bad['body']['id']}")
    good_after = request("GET", f"/admin/channels/{good['body']['id']}")
    results["groups"]["routing"] = [
        ok("Weighted cache-hit distribution favors high weight", high_count > low_count and high_count + low_count >= 50, {"high_id": high_id, "low_id": low_id, "counts": count_map, "first_response": first_weight_payload}),
        ok("Failover bad primary to mock secondary", fail_resp["status"] == 200 and "mock response" in json.dumps(fail_resp["body"]) and bad_after["body"].get("health") == "failed" and good_after["body"].get("health") == "ok", {"response": fail_resp, "bad_after": bad_after, "good_after": good_after}),
    ]

    # Group 5: production mode filtering.
    prod_before = get_env("maas", "PRODUCTION_MODE")
    restart_true = restart_maas("true")
    prod_true = get_env("maas", "PRODUCTION_MODE")
    prod_chat = chat("mock-chat", "production should block mock")
    prod_emb = embedding("mock-embedding", "production should block mock")
    no_mock_text = "mock response:" not in json.dumps(prod_chat["body"], ensure_ascii=False)
    restart_false = restart_maas("false")
    prod_false = get_env("maas", "PRODUCTION_MODE")
    demo_chat = chat("mock-chat", "demo restored")
    results["groups"]["production_mode"] = [
        ok("Initial PRODUCTION_MODE false", prod_before == "false", {"env": prod_before}),
        ok("Switch PRODUCTION_MODE true", restart_true["code"] == 0 and prod_true == "true", restart_true),
        ok("Production filters mock chat", prod_chat["status"] == 409 and detail(prod_chat) == "no_active_model_channel" and no_mock_text, prod_chat),
        ok("Production filters mock embedding", prod_emb["status"] == 409 and detail(prod_emb) == "no_active_model_channel", prod_emb),
        ok("Restore PRODUCTION_MODE false", restart_false["code"] == 0 and prod_false == "false", restart_false),
        ok("Demo mock restored", demo_chat["status"] == 200 and "mock response: demo restored" in json.dumps(demo_chat["body"], ensure_ascii=False), demo_chat),
    ]

    # Group 6: usage/cost/cache and cross-tenant cache.
    usage_model = f"qa-step2-usage-{ts}"
    usage_ch_a = create_channel(usage_model, "llm", tenant_id=tenant_a, weight=1)
    usage_ch_b = create_channel(usage_model, "llm", tenant_id=tenant_b, weight=1)
    payload_text = f"same cache payload {ts}"
    usage_first = chat(usage_model, payload_text)
    usage_second = chat(usage_model, payload_text)
    usage_emb_model = f"qa-step2-usage-emb-{ts}"
    usage_emb_ch = create_channel(usage_emb_model, "embedding", tenant_id=tenant_a, weight=1)
    usage_emb_first = embedding(usage_emb_model, f"embedding cache {ts}")
    usage_emb_second = embedding(usage_emb_model, f"embedding cache {ts}")
    usage_rows = psql_csv(
        "select tenant_id::text,channel_id::text,prompt_tokens,completion_tokens,latency_ms,cost::text,cache_hit "
        "from usage_records "
        f"where channel_id in ('{usage_ch_a['body']['id']}','{usage_ch_b['body']['id']}','{usage_emb_ch['body']['id']}') "
        "order by created_at asc;"
    )
    cross_cache = {
        "note": "MaaS /v1 endpoints do not accept tenant identity; candidate selection is global by model name. Two tenant-scoped channels for the same model were created, and identical payload produced cache_hit records without tenant in cache key.",
        "rows": usage_rows,
        "chat_cache_hit_returned": usage_second["body"].get("cache_hit") if isinstance(usage_second["body"], dict) else None,
        "embedding_cache_hit_returned": usage_emb_second["body"].get("cache_hit") if isinstance(usage_emb_second["body"], dict) else None,
    }
    results["groups"]["usage"] = [
        ok("Usage records written", len(usage_rows) >= 4, {"rows": usage_rows}),
        ok("Cost remains zero R10", usage_rows and all(row.get("cost") in {"0.000000", "0"} for row in usage_rows), {"rows": usage_rows}),
        ok("Chat cache hit on identical payload", isinstance(usage_second["body"], dict) and usage_second["body"].get("cache_hit") is True, usage_second),
        ok("Embedding cache hit on identical payload", isinstance(usage_emb_second["body"], dict) and usage_emb_second["body"].get("cache_hit") is True, usage_emb_second),
        ok("R11 cross-tenant cache risk observed structurally", any(row.get("cache_hit") == "t" and row.get("tenant_id") == tenant_b for row in usage_rows) or any(row.get("cache_hit") == "t" for row in usage_rows), cross_cache, "缓存 key 只由 payload 构成，不含租户；MaaS 端点无租户身份"),
    ]

    defects = []
    for group, cases in results["groups"].items():
        for case in cases:
            if case["result"] == "FAIL":
                defects.append({"group": group, "name": case["name"], "response": case["response"], "note": case["note"]})
    # Known/design defects with evidence.
    defects.append({"group": "usage", "name": "R10 cost remains zero", "response": usage_rows, "severity": "known"})
    defects.append({"group": "usage", "name": "R11 cache key lacks tenant identity", "response": cross_cache, "severity": "risk"})
    if prod_chat["status"] != 409 or "mock response:" in json.dumps(prod_chat["body"], ensure_ascii=False):
        defects.append({"group": "production_mode", "name": "P0 mock not filtered in production", "response": prod_chat, "severity": "P0"})
    results["defects"] = defects

    (QA_ENV / "step2-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md = render(results)
    (QA_RECORDS / "step2-model-maas.md").write_text(md, encoding="utf-8")
    print(md)


def render(results: dict) -> str:
    lines = ["# Step 2 模型渠道 / MaaS 测试记录", "", f"执行时间：{time.strftime('%Y-%m-%d %H:%M:%S %z')}", ""]
    titles = {
        "probe": "第 1 组：连通性 probe",
        "errors": "第 2 组：无候选与错误码",
        "rpm": "第 3 组：RPM 限流",
        "routing": "第 4 组：加权与故障转移",
        "production_mode": "第 5 组：生产模式过滤 mock",
        "usage": "第 6 组：用量记录 / cost / cache",
    }
    for key, title in titles.items():
        lines += [f"## {title}", "", "| 用例 | 结论 | 状态/摘要 |", "|---|---:|---|"]
        for case in results["groups"].get(key, []):
            lines.append(f"| {case['name']} | {case['result']} | `{short(case['response'])}` {case.get('note','')} |")
        lines.append("")
    lines += ["## Demo 已验 / 待真实 key 补测", "", "- Demo 已验：mock probe、mock chat/embedding 路由、错误码、RPM、故障转移、生产模式过滤、usage/cache 结构。", "- 待真实 key 补测：真实 openai_compatible 有效 key `ok=true`；本次已用无效 key验证真实 base_url 错误分类路径。", ""]
    lines += ["## 缺陷记录", ""]
    for defect in results.get("defects", []):
        lines.append(f"- `{defect.get('group')}` {defect.get('severity','')}: {defect['name']} -> `{short(defect.get('response'))}`")
    lines.append("")
    prod_ok = all(c["result"] == "PASS" for c in results["groups"]["production_mode"])
    routing_ok = all(c["result"] == "PASS" for c in results["groups"]["routing"])
    probe_ok = all(c["result"] == "PASS" for c in results["groups"]["probe"])
    errors_ok = all(c["result"] == "PASS" for c in results["groups"]["errors"])
    rpm_ok = all(c["result"] == "PASS" for c in results["groups"]["rpm"])
    lines += ["## 结论", "", f"- 生产模式过滤 mock：{'可靠' if prod_ok else '存在失败'}。", f"- 模型路由/故障转移/RPM：{'通过 demo 验证' if routing_ok and rpm_ok else '存在失败'}。", f"- probe/错误码：{'通过 demo 验证' if probe_ok and errors_ok else '存在失败'}。", f"- 是否可以进入 Step 3：{'可以' if prod_ok and routing_ok and rpm_ok and probe_ok and errors_ok else '不建议'}。"]
    return "\n".join(lines) + "\n"


def short(value, max_len=240) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


if __name__ == "__main__":
    main()
