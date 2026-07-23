import concurrent.futures
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "qa" / "env"
BASE = "http://localhost:8200"


def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def sandbox_exec(payload, *, timeout=45):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE + "/exec",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            body = parse_json(text)
            status = resp.status
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        body = parse_json(text) or text
        status = exc.code
    except Exception as exc:
        body = {"error": type(exc).__name__, "detail": str(exc)}
        status = "client_error"
    elapsed = round(time.perf_counter() - started, 3)
    return {"status": status, "elapsed_sec": elapsed, "body": body}


def curl_health(url):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "elapsed_sec": round(time.perf_counter() - started, 3), "body": parse_json(text) or text}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc), "elapsed_sec": round(time.perf_counter() - started, 3)}


def compose(*args, timeout=30):
    proc = subprocess.run(["docker", "compose", *args], cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def health_snapshot():
    return {
        "backend": curl_health("http://localhost:8001/healthz"),
        "maas": curl_health("http://localhost:8100/healthz"),
        "sandbox": curl_health("http://localhost:8200/healthz"),
    }


def py(code, timeout_seconds=10):
    return {"type": "python", "code": code, "timeout_seconds": timeout_seconds}


def main():
    ts = str(int(time.time()))
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    env = compose("exec", "-T", "sandbox", "env")
    user_info = compose("exec", "-T", "sandbox", "id")

    results = {
        "ts": ts,
        "git_head": git_head,
        "method": "direct localhost:8200/exec",
        "sandbox_env": env,
        "container_id": user_info,
        "health_before": health_snapshot(),
        "groups": {},
    }

    results["groups"]["1_allowlist"] = {
        "command_ls": sandbox_exec({"type": "command", "command": ["ls"], "timeout_seconds": 3}),
        "command_bash": sandbox_exec({"type": "command", "command": ["bash", "-c", "id"], "timeout_seconds": 3}),
        "python_empty_code": sandbox_exec({"type": "python", "code": "", "timeout_seconds": 3}),
    }
    results["health_after_group1"] = health_snapshot()

    results["groups"]["2_timeout"] = {
        "while_true_timeout_2": sandbox_exec(py("while True:\n    pass\n", timeout_seconds=2), timeout=15)
    }
    results["health_after_group2"] = health_snapshot()

    memory_code = """
import sys
try:
    data = bytearray(600 * 1024 * 1024)
    print("allocated", len(data))
except BaseException as exc:
    print(type(exc).__name__ + ":" + str(exc))
    sys.exit(42)
"""
    fork_code = """
import os, sys, time
children = []
failures = []
for i in range(100):
    try:
        pid = os.fork()
        if pid == 0:
            time.sleep(0.5)
            os._exit(0)
        children.append(pid)
    except OSError as exc:
        failures.append(f"{type(exc).__name__}:{exc.errno}:{exc.strerror}")
        break
for pid in children:
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
print({"forked": len(children), "failures": failures[:3]})
sys.exit(0 if failures else 43)
"""
    nofile_code = """
import os, tempfile, sys
fds = []
try:
    for i in range(200):
        fds.append(open('/dev/null', 'rb'))
except OSError as exc:
    print(f"OSError:{exc.errno}:{exc.strerror}; opened={len(fds)}")
    sys.exit(0)
print(f"opened={len(fds)} without_error")
sys.exit(44)
"""
    cpu_code = """
import time
started = time.time()
x = 0
while True:
    x += 1
    if x % 10000000 == 0 and time.time() - started > 20:
        print("unexpected_survived")
        break
"""
    results["groups"]["3_rlimit"] = {
        "memory_600mb": sandbox_exec(py(memory_code, timeout_seconds=8), timeout=20),
        "nproc_fork_100": sandbox_exec(py(fork_code, timeout_seconds=8), timeout=20),
        "nofile_open_200": sandbox_exec(py(nofile_code, timeout_seconds=8), timeout=20),
        "cpu_busy": sandbox_exec(py(cpu_code, timeout_seconds=10), timeout=20),
    }
    results["health_after_group3"] = health_snapshot()

    slow_code = "import time\nprint('start')\ntime.sleep(3)\nprint('done')\n"
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(sandbox_exec, py(slow_code, timeout_seconds=8), timeout=20) for _ in range(4)]
        concurrent_outputs = [future.result() for future in futures]
    results["groups"]["4_concurrency"] = {
        "total_elapsed_sec": round(time.perf_counter() - started, 3),
        "requests": concurrent_outputs,
    }
    results["health_after_group4"] = health_snapshot()

    identity_code = """
import os, pwd, subprocess
print({"uid": os.getuid(), "gid": os.getgid(), "user": pwd.getpwuid(os.getuid()).pw_name})
try:
    print("whoami=" + subprocess.check_output(["whoami"], text=True).strip())
except Exception as exc:
    print("whoami_error=" + type(exc).__name__ + ":" + str(exc))
"""
    shadow_code = """
for path in ["/etc/shadow", "/root/.ssh/id_rsa", "/data/secrets/test"]:
    try:
        with open(path, "rb") as f:
            data = f.read(80)
        print(path + ":READ:" + repr(data[:30]))
    except Exception as exc:
        print(path + ":" + type(exc).__name__ + ":" + str(exc))
"""
    network_code = """
import socket, json
targets = [
    ("postgres", 5432),
    ("maas", 8100),
    ("backend", 8001),
    ("minio", 9000),
]
out = {}
for host, port in targets:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect((host, port))
        out[f"{host}:{port}"] = "connected"
    except Exception as exc:
        out[f"{host}:{port}"] = type(exc).__name__ + ":" + str(exc)
    finally:
        try:
            s.close()
        except Exception:
            pass
print(json.dumps(out, ensure_ascii=False, sort_keys=True))
"""
    http_network_code = """
import urllib.request, json
targets = ["http://maas:8100/healthz", "http://backend:8001/healthz"]
out = {}
for url in targets:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            out[url] = {"status": resp.status, "body": resp.read(120).decode("utf-8", "replace")}
    except Exception as exc:
        out[url] = type(exc).__name__ + ":" + str(exc)
print(json.dumps(out, ensure_ascii=False, sort_keys=True))
"""
    results["groups"]["5_identity_escape_network"] = {
        "identity": sandbox_exec(py(identity_code, timeout_seconds=5), timeout=12),
        "sensitive_paths": sandbox_exec(py(shadow_code, timeout_seconds=5), timeout=12),
        "tcp_internal_connectivity": sandbox_exec(py(network_code, timeout_seconds=5), timeout=12),
        "http_internal_healthz": sandbox_exec(py(http_network_code, timeout_seconds=5), timeout=12),
    }
    results["health_after_group5"] = health_snapshot()
    results["docker_compose_ps"] = compose("ps")
    results["sandbox_logs_tail"] = compose("logs", "--tail=120", "sandbox")

    (ENV / "step7-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Step 7 Runner Output",
        "",
        f"- ts: `{ts}`",
        f"- git HEAD: `{git_head}`",
        "- method: `direct localhost:8200/exec`",
        f"- sandbox env relevant: `{', '.join(line for line in env['stdout'].splitlines() if any(k in line for k in ['CPU_SECONDS', 'MEMORY_MB', 'MAX_OPEN_FILES', 'MAX_PROCESSES', 'MAX_CONCURRENCY']))}`",
        "",
    ]
    for group_name, group in results["groups"].items():
        lines += [f"## {group_name}", "```json", json.dumps(group, ensure_ascii=False, indent=2), "```", ""]
    lines += ["## health_after_group5", "```json", json.dumps(results["health_after_group5"], ensure_ascii=False, indent=2), "```"]
    (ENV / "step7-runner-output.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
