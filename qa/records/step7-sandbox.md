# Step 7 Sandbox 系统层隔离测试记录

- 测试时间戳：`1784006206`
- git HEAD：`aeb7bd5e4a8e4d30783eb4648df4e93f85483728`
- 测试入口：直接调用 `POST http://localhost:8200/exec`
- sandbox 当前环境：`CPU_SECONDS=5`，`MEMORY_MB=256`，`MAX_OPEN_FILES=64`，`MAX_PROCESSES=32`，`MAX_CONCURRENCY=2`
- 原始结果：`qa/env/step7-results.json`
- Runner 摘要：`qa/env/step7-runner-output.md`
- 脚本：`qa/scripts/step7_sandbox_runner.py`

## 代码证据

- `sandbox/app/api/exec.py:14-15`：命令白名单为 `{"python", "python3"}`，并使用 `asyncio.Semaphore(settings.max_concurrency)` 控制并发。
- `sandbox/app/api/exec.py:18-30`：`type=python` 空 code 返回 `code_required`；`type=command` 且首命令不在白名单返回 `command_not_allowed`。
- `sandbox/app/api/exec.py:40-61`：子进程在信号量内执行；超时后 `process.kill()`，返回 `timed_out=true`。
- `sandbox/app/api/exec.py:64-70`：子进程设置 `RLIMIT_CPU`、`RLIMIT_AS`、`RLIMIT_NOFILE`、`RLIMIT_NPROC`。
- `sandbox/Dockerfile:13-14`：创建并切换到 `uid=10001` 的 `sandbox` 用户。

## 第 1 组：命令白名单

| 用例 | 实际 | 结论 |
|---|---|---|
| `type=command`, `["ls"]` | HTTP `400`，`detail=command_not_allowed` | PASS |
| `type=command`, `["bash","-c","id"]` | HTTP `400`，`detail=command_not_allowed` | PASS |
| `type=python`, 空 code | HTTP `422`，`detail=code_required` | PASS |

结论：命令白名单对 `command` 类型生效；`python` 类型仅允许提交 Python 代码文本。

## 第 2 组：超时

| 用例 | timeout | 实际耗时 | 退出码 | timed_out | 结论 |
|---|---:|---:|---:|---|---|
| `while True: pass` | 2s | 2.011s | `-9` | `true` | PASS |

结论：接口能在配置 timeout 附近返回，进程被 kill，没有永久挂起。

## 第 3 组：资源限制 rlimit

| 限制项 | 构造 | 实际结果 | 宿主/服务状态 | 结论 |
|---|---|---|---|---|
| 内存 `RLIMIT_AS=256MB` | `bytearray(600MB)` | `MemoryError`，exit_code=`42`，0.014s 返回 | backend/MaaS/sandbox healthz 正常 | PASS |
| 进程数 `RLIMIT_NPROC=32` | 温和 fork 到最多 100 个子进程 | fork 到 `25` 后 `BlockingIOError: Resource temporarily unavailable` | healthz 正常 | PASS |
| 文件数 `RLIMIT_NOFILE=64` | 打开 200 个 `/dev/null` 句柄 | 打开 `58` 个后 `OSError:24 Too many open files` | healthz 正常 | PASS |
| CPU `RLIMIT_CPU=5s` | CPU 密集循环 | 5.019s 返回，exit_code=`-24`，`timed_out=false` | healthz 正常 | PASS |

结论：本轮验证中四类 rlimit 均真实生效。CPU 用例由 `RLIMIT_CPU` 触发，早于接口 timeout；内存/进程/文件触限都没有拖垮宿主。

## 第 4 组：并发上限

构造：并发提交 4 个 `sleep 3` 的 Python 任务，`MAX_CONCURRENCY=2`。

| 指标 | 实际 |
|---|---|
| 总耗时 | 6.056s |
| 前两条请求耗时 | 约 3.02s |
| 后两条请求耗时 | 约 6.05s |
| 预期 | 两批执行，约 6s |

结论：全局信号量生效，未同时启动 4 个慢任务。

## 第 5 组：非 root 与逃逸面

### 非 root

| 检查 | 实际 | 结论 |
|---|---|---|
| 容器 `id` | `uid=10001(sandbox) gid=10001(sandbox)` | PASS |
| Python `os.getuid()` | `uid=10001, gid=10001, user=sandbox` | PASS |
| `whoami` | `sandbox` | PASS |

### 敏感路径读取

| 路径 | 实际 |
|---|---|
| `/etc/shadow` | `PermissionError: [Errno 13] Permission denied` |
| `/root/.ssh/id_rsa` | `PermissionError: [Errno 13] Permission denied` |
| `/data/secrets/test` | `FileNotFoundError` |

结论：非 root 身份生效，常见敏感路径无法直接读取。

### 网络出站 / 内网访问

| 目标 | 实际 |
|---|---|
| `postgres:5432` | TCP `connected` |
| `maas:8100` | TCP `connected` |
| `backend:8001` | TCP `connected` |
| `minio:9000` | TCP `connected` |
| `http://maas:8100/healthz` | HTTP `200`，返回 MaaS healthz |
| `http://backend:8001/healthz` | HTTP `200`，返回 backend healthz |

结论：**sandbox 没有网络隔离**，可访问 Docker 内网关键服务。测试仅做连接和 healthz 观测，未读写数据、未外连公网。

## 服务稳定性

触限测试后：

| 服务 | healthz |
|---|---|
| backend | `200 ok` |
| MaaS | `200 ok` |
| sandbox | `200 ok` |

`docker compose ps` 显示 backend、frontend、MaaS、MinIO、Postgres、Redis、sandbox 均处于 Up，MinIO/Postgres/Redis 为 healthy。

## 缺陷与风险

| 编号 | 严重度 | 状态 | 证据 | 影响 |
|---|---|---|---|---|
| R1-叠加风险 | P0 | 已证实 | Step 6 已证实 code 工具可直连执行；本步证实 sandbox 可访问内网 backend/MaaS/Postgres/MinIO | 攻击者若能触发 code 工具，可在 sandbox 内探测/访问内网服务 |
| S1 | P1 | 已证实 | sandbox TCP 可连 `postgres:5432`、`maas:8100`、`backend:8001`、`minio:9000` | sandbox 缺少网络 egress 隔离，R1 成立时风险显著放大 |

非缺陷但需关注：

- rlimit 对 CPU/内存/进程/文件数有效。
- 非 root 有效。
- command 白名单有效。
- 并发上限有效。

## Step 7 结论

sandbox 作为**进程级资源隔离防线基本可靠**：命令白名单、超时、CPU/内存/进程/文件 rlimit、并发上限、非 root 均通过本轮验证。

但 sandbox 作为**安全边界不完整**：没有网络出站隔离，能访问 Docker 内网关键服务。结合 Step 6 的 R1 “code 工具可直连执行”，实际风险为：租户 builder 可通过 code 工具进入 sandbox，再从 sandbox 发起内网探测/访问。虽然 sandbox 资源限制能防止简单资源耗尽，但不能防止内网横向访问。

是否进入 Step 8：测试流程可以继续；发布风险上，R1 + sandbox 无网络隔离应作为阻断级安全风险联动处理。
