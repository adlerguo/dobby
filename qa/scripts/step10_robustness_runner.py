import concurrent.futures
import http.client
import json
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "qa" / "env"
BASE = "http://localhost:8001/api/v1"
MAAS = "http://localhost:8100"


def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def req(method, path, *, token=None, json_body=None, raw_body=None, content_type="application/json", timeout=20, base=BASE):
    if raw_body is not None:
        data = raw_body
    elif json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
    else:
        data = None
    headers = {}
    if data is not None and content_type is not None:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "elapsed_sec": round(time.perf_counter() - started, 3), "body": parse_json(text) if parse_json(text) is not None else text}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "elapsed_sec": round(time.perf_counter() - started, 3), "body": parse_json(text) if parse_json(text) is not None else text}
    except Exception as exc:
        return {"status": "client_error", "elapsed_sec": round(time.perf_counter() - started, 3), "body": {"error": type(exc).__name__, "detail": str(exc)}}


def compose(*args, timeout=120):
    proc = subprocess.run(["docker", "compose", *args], cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def login(tenant_code, username, password):
    return req("POST", "/auth/login", json_body={"tenant_code": tenant_code, "username": username, "password": password})


def healthz():
    return {
        "backend": req("GET", "/healthz", timeout=5),
        "maas": req("GET", "/healthz", timeout=5, base=MAAS, path_override=True) if False else raw_url("http://localhost:8100/healthz"),
        "sandbox": raw_url("http://localhost:8200/healthz"),
        "frontend": raw_url("http://localhost:18080", timeout=5),
    }


def raw_url(url, timeout=5):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            text = resp.read(500).decode("utf-8", errors="replace")
            return {"status": resp.status, "elapsed_sec": round(time.perf_counter() - started, 3), "body": parse_json(text) if parse_json(text) is not None else text[:200]}
    except Exception as exc:
        return {"status": "client_error", "elapsed_sec": round(time.perf_counter() - started, 3), "body": {"error": type(exc).__name__, "detail": str(exc)}}


def wait_service(service, seconds=40):
    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        last = compose("ps", service)
        if "Up" in last["stdout"]:
            if service == "postgres" and "healthy" not in last["stdout"]:
                time.sleep(1)
                continue
            if service in {"redis", "minio"} and "healthy" not in last["stdout"] and service != "redis":
                time.sleep(1)
                continue
            return {"ok": True, "ps": last}
        time.sleep(1)
    return {"ok": False, "ps": last}


def restore_services():
    out = {"start": compose("start", "postgres", "redis", "minio", "maas", "sandbox", timeout=180)}
    for service in ["postgres", "redis", "minio", "maas", "sandbox"]:
        out[f"wait_{service}"] = wait_service(service)
    time.sleep(2)
    out["healthz"] = healthz()
    out["ps"] = compose("ps")
    return out


def make_tool(token, ts):
    return req("POST", "/tools", token=token, json_body={"name": f"QA Step10 Code Tool {ts}", "type": "code", "schema": {}, "config": {}})


def run_code_tool(token, tool_id):
    return req("POST", f"/tools/{tool_id}/run", token=token, json_body={"input": {"code": "print('step10 sandbox dependency')", "timeout_seconds": 3}}, timeout=12)


def curl_upload(token, kb_id, file_path):
    started = time.perf_counter()
    proc = subprocess.run(
        [
            "curl",
            "-sS",
            "-w",
            "\nHTTP_STATUS:%{http_code}",
            "-H",
            f"Authorization: Bearer {token}",
            "-F",
            f"file=@{file_path};type=text/plain",
            f"{BASE}/kbs/{kb_id}/documents",
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    text = proc.stdout
    status = None
    body = text
    if "\nHTTP_STATUS:" in text:
        body, status_text = text.rsplit("\nHTTP_STATUS:", 1)
        try:
            status = int(status_text.strip())
        except ValueError:
            status = status_text.strip()
    return {
        "status": status,
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "body": parse_json(body) if parse_json(body) is not None else body[:2000],
        "stderr": proc.stderr[:2000],
        "returncode": proc.returncode,
    }


def sse_disconnect(token, agent_id, query):
    body = json.dumps({"agent_id": agent_id, "query": query, "max_tool_rounds": 0}).encode("utf-8")
    try:
        sock = socket.create_connection(("localhost", 8001), timeout=5)
        req_bytes = (
            b"POST /api/v1/chat HTTP/1.1\r\n"
            b"Host: localhost:8001\r\n"
            + f"Authorization: Bearer {token}\r\n".encode()
            + b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        sock.sendall(req_bytes)
        sock.close()
        return {"status": "closed_immediately"}
    except Exception as exc:
        return {"status": "client_error", "error": type(exc).__name__, "detail": str(exc)}


def backend_logs_tail(lines=120):
    return compose("logs", f"--tail={lines}", "backend")


def main():
    ts = str(int(time.time()))
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    step1 = json.loads((ENV / "step1-fixtures.json").read_text(encoding="utf-8"))
    tenant_a = step1["tenants"]["A"]
    alice = step1["users"]["alice"]
    agent_a = step1["resources"]["A"]["agent_id"]
    kb_a = step1["resources"]["A"]["kb_id"]
    tool_a = step1["resources"]["A"]["tool_id"]
    login_a = login(tenant_a["code"], alice["username"], alice["password"])
    token = login_a["body"]["access_token"]
    production_mode = compose("exec", "-T", "maas", "printenv", "PRODUCTION_MODE")

    results = {
        "ts": ts,
        "git_head": git_head,
        "production_mode": production_mode,
        "baseline": {"healthz": healthz(), "ps": compose("ps")},
        "groups": {},
        "restore": {},
    }

    try:
        long_query = "超长输入 " + ("x" * 60000)
        huge_query = "huge " + ("y" * (1024 * 1024))
        deep = '"x"'
        for _ in range(600):
            deep = "[" + deep + "]"
        invalid_uuid = "not-a-uuid"
        results["groups"]["1_invalid_inputs"] = {
            "empty_query": req("POST", f"/agents/{agent_a}/run", token=token, json_body={"query": "", "max_tool_rounds": 0}),
            "long_query": req("POST", f"/agents/{agent_a}/run", token=token, json_body={"query": long_query, "max_tool_rounds": 0}, timeout=60),
            "huge_json_body": req("POST", f"/agents/{agent_a}/run", token=token, json_body={"query": huge_query, "max_tool_rounds": 0}, timeout=60),
            "invalid_utf8": req("POST", f"/agents/{agent_a}/run", token=token, raw_body=b'{"query":"\\xff","max_tool_rounds":0}', timeout=20),
            "deep_nested_json": req("POST", f"/agents/{agent_a}/run", token=token, raw_body=(b'{"query":"x","max_tool_rounds":0,"extra":' + deep.encode() + b"}"), timeout=20),
            "wrong_content_type": req("POST", f"/agents/{agent_a}/run", token=token, raw_body=b'{"query":"x","max_tool_rounds":0}', content_type="text/plain", timeout=20),
            "invalid_uuid_agent": req("GET", f"/agents/{invalid_uuid}", token=token),
            "invalid_uuid_kb": req("GET", f"/kbs/{invalid_uuid}", token=token),
            "invalid_uuid_tool": req("GET", f"/tools/{invalid_uuid}", token=token),
        }

        code_tool = make_tool(token, ts)
        code_tool_id = code_tool["body"]["id"] if code_tool["status"] == 201 else None
        fixture_file = ROOT / "qa" / "env" / f"step10-upload-{ts}.txt"
        fixture_file.write_text(f"step10 upload fixture {ts}\n", encoding="utf-8")

        dep = {}

        compose("stop", "redis", timeout=60)
        dep["redis_stopped_ps"] = compose("ps", "redis")
        dep["redis_login"] = login(tenant_a["code"], alice["username"], alice["password"])
        dep["redis_backend_chat"] = req("POST", f"/agents/{agent_a}/run", token=token, json_body={"query": f"redis down chat {ts}", "max_tool_rounds": 0}, timeout=30)
        dep["redis_maas_chat"] = req("POST", "/v1/chat/completions", base=MAAS, json_body={"model": "mock-chat", "messages": [{"role": "user", "content": "ping"}]}, timeout=20)
        dep["redis_restore"] = compose("start", "redis", timeout=60)
        dep["redis_wait"] = wait_service("redis")

        compose("stop", "minio", timeout=60)
        dep["minio_stopped_ps"] = compose("ps", "minio")
        dep["minio_upload"] = curl_upload(token, kb_a, fixture_file)
        dep["minio_retrieve"] = req("POST", f"/kbs/{kb_a}/retrieve", token=token, json_body={"query": "private document", "top_k": 2, "match_type": "hybrid"}, timeout=30)
        dep["minio_restore"] = compose("start", "minio", timeout=60)
        dep["minio_wait"] = wait_service("minio")

        compose("stop", "maas", timeout=60)
        dep["maas_stopped_ps"] = compose("ps", "maas")
        dep["maas_backend_chat"] = req("POST", f"/agents/{agent_a}/run", token=token, json_body={"query": f"maas down chat {ts}", "max_tool_rounds": 0}, timeout=30)
        dep["maas_health"] = raw_url("http://localhost:8100/healthz", timeout=5)
        dep["maas_restore"] = compose("start", "maas", timeout=60)
        dep["maas_wait"] = wait_service("maas")
        time.sleep(2)

        compose("stop", "sandbox", timeout=60)
        dep["sandbox_stopped_ps"] = compose("ps", "sandbox")
        dep["sandbox_code_tool_run"] = run_code_tool(token, code_tool_id) if code_tool_id else {"status": "skipped"}
        dep["sandbox_restore"] = compose("start", "sandbox", timeout=60)
        dep["sandbox_wait"] = wait_service("sandbox")

        compose("stop", "postgres", timeout=60)
        dep["postgres_stopped_ps"] = compose("ps", "postgres")
        dep["postgres_agents"] = req("GET", "/agents", token=token, timeout=15)
        dep["postgres_auth_me"] = req("GET", "/auth/me", token=token, timeout=15)
        dep["postgres_restore"] = compose("start", "postgres", timeout=90)
        dep["postgres_wait"] = wait_service("postgres", seconds=60)
        time.sleep(3)
        dep["post_restore_login"] = login(tenant_a["code"], alice["username"], alice["password"])
        results["groups"]["2_dependency_faults"] = dep

        before_logs = backend_logs_tail(80)
        one_disconnect = sse_disconnect(token, agent_a, f"sse disconnect {ts}")
        time.sleep(2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            multi_disconnect = list(pool.map(lambda i: sse_disconnect(token, agent_a, f"sse multi {ts}-{i}"), range(5)))
        time.sleep(2)
        after_logs = backend_logs_tail(160)
        results["groups"]["3_sse_disconnect"] = {
            "one_disconnect": one_disconnect,
            "multi_disconnect": multi_disconnect,
            "backend_logs_before_tail": before_logs,
            "backend_logs_after_tail": after_logs,
        }

        def chat_task(i, conv_id=None):
            payload = {"query": f"step10 concurrent {ts}-{i}", "max_tool_rounds": 0}
            if conv_id:
                payload["conversation_id"] = conv_id
            started = time.perf_counter()
            r = req("POST", f"/agents/{agent_a}/run", token=token, json_body=payload, timeout=90)
            r["task_elapsed_sec"] = round(time.perf_counter() - started, 3)
            return r

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            concurrent_chats = list(pool.map(chat_task, range(10)))

        upload_files = []
        for i in range(5):
            p = ROOT / "qa" / "env" / f"step10-concurrent-upload-{ts}-{i}.txt"
            p.write_text(f"step10 concurrent upload {ts}-{i}\n", encoding="utf-8")
            upload_files.append(p)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            concurrent_uploads = list(pool.map(lambda p: curl_upload(token, kb_a, p), upload_files))

        initial_conv = chat_task("base")
        conv_id = initial_conv.get("body", {}).get("conversation_id") if initial_conv["status"] == 200 else None
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            same_conv_runs = list(pool.map(lambda i: chat_task(f"sameconv-{i}", conv_id), range(5))) if conv_id else []
        same_conv_messages = req("GET", f"/conversations/{conv_id}/messages", token=token) if conv_id else None

        results["groups"]["4_concurrency_races"] = {
            "concurrent_chats": concurrent_chats,
            "concurrent_uploads": concurrent_uploads,
            "same_conversation_initial": initial_conv,
            "same_conversation_runs": same_conv_runs,
            "same_conversation_messages": same_conv_messages,
        }

        r4_code = {
            "backend_call_maas_chat_stream_timeout_none": "backend/app/orchestrator/runtime.py uses httpx.AsyncClient(timeout=None) in call_maas_chat_stream",
            "maas_proxy_openai_stream_timeout_none": "maas/app/services.py uses httpx.AsyncClient(timeout=None) in proxy_openai_stream",
            "demo_hang_simulation": "not executed; robust hang simulation needs a controllable slow upstream/toxiproxy or real provider endpoint",
        }
        results["groups"]["5_r4_stream_timeout"] = r4_code

    finally:
        results["restore"] = restore_services()
        (ENV / "step10-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = summarize(results)
    (ENV / "step10-runner-output.md").write_text("# Step 10 Runner Output\n\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def summarize(results):
    dep = results.get("groups", {}).get("2_dependency_faults", {})
    invalid = results.get("groups", {}).get("1_invalid_inputs", {})
    conc = results.get("groups", {}).get("4_concurrency_races", {})
    conc_post = results.get("groups", {}).get("4_concurrency_races_post_restore", {})
    return {
        "ts": results["ts"],
        "production_mode": results["production_mode"]["stdout"].strip(),
        "invalid_input_statuses": {k: v.get("status") for k, v in invalid.items()},
        "dependency_statuses": {
            "redis_login": dep.get("redis_login", {}).get("status"),
            "redis_backend_chat": dep.get("redis_backend_chat", {}).get("status"),
            "redis_maas_chat": dep.get("redis_maas_chat", {}).get("status"),
            "minio_upload": dep.get("minio_upload", {}).get("status"),
            "minio_retrieve": dep.get("minio_retrieve", {}).get("status"),
            "maas_backend_chat": dep.get("maas_backend_chat", {}).get("status"),
            "sandbox_code_tool_run": dep.get("sandbox_code_tool_run", {}).get("status"),
            "postgres_agents": dep.get("postgres_agents", {}).get("status"),
            "postgres_auth_me": dep.get("postgres_auth_me", {}).get("status"),
            "post_restore_login": dep.get("post_restore_login", {}).get("status"),
        },
        "concurrent_chat_status_counts": count_statuses(conc.get("concurrent_chats", [])),
        "concurrent_upload_status_counts": count_statuses(conc.get("concurrent_uploads", [])),
        "same_conversation_status_counts": count_statuses(conc.get("same_conversation_runs", [])),
        "same_conversation_message_count": (
            len(conc.get("same_conversation_messages", {}).get("body", []))
            if isinstance(conc.get("same_conversation_messages"), dict)
            and isinstance(conc.get("same_conversation_messages", {}).get("body"), list)
            else None
        ),
        "r4": results.get("groups", {}).get("5_r4_stream_timeout"),
        "post_restore_channel_fix": results.get("post_restore_channel_fix"),
        "post_restore_concurrent_chat_status_counts": count_statuses(conc_post.get("concurrent_chats", [])),
        "post_restore_same_conversation_status_counts": count_statuses(conc_post.get("same_conversation_runs", [])),
        "post_restore_same_conversation_message_count": (
            len(conc_post.get("same_conversation_messages", {}).get("body", []))
            if isinstance(conc_post.get("same_conversation_messages"), dict)
            and isinstance(conc_post.get("same_conversation_messages", {}).get("body"), list)
            else None
        ),
        "restore_healthz": results.get("restore", {}).get("healthz"),
        "restore_after_channel_fix_healthz": results.get("restore_after_channel_fix", {}).get("healthz"),
        "restore_ps": results.get("restore", {}).get("ps", {}).get("stdout"),
    }


def count_statuses(items):
    counts = {}
    for item in items:
        key = str(item.get("status"))
        counts[key] = counts.get(key, 0) + 1
    return counts


if __name__ == "__main__":
    main()
