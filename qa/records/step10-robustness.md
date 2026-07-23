# Step 10 鲁棒性与故障注入测试记录

- 测试时间戳：`1784013275`
- git HEAD：`aeb7bd5e4a8e4d30783eb4648df4e93f85483728`
- MaaS `PRODUCTION_MODE`：`false`
- 测试脚本：`qa/scripts/step10_robustness_runner.py`
- 原始结果：`qa/env/step10-results.json`
- 摘要输出：`qa/env/step10-runner-output.md`

## 基线与恢复

测试前：

- backend、frontend、MaaS、MinIO、Postgres、Redis、sandbox 均 Up。
- MaaS `PRODUCTION_MODE=false`。

测试后：

- backend `/healthz`：`200 ok`
- MaaS `/healthz`：`200 ok`
- sandbox `/healthz`：`200 ok`
- frontend `/`：`200`
- `docker compose ps`：Postgres/Redis/MinIO healthy；backend/MaaS/sandbox/frontend Up。
- mock 直连：`POST /v1/chat/completions model=mock-chat` 返回 `200 mock response`。
- A agent 基线对话恢复后返回 `200`。

补充恢复动作：

- 故障注入后 `mock-embedding` 渠道 health 被标记为 `failed`，导致 A agent RAG 对话持续 `409 no_active_model_channel`。
- 已将 `mock-chat/mock-embedding` 的 `mock://local` 测试渠道恢复为 `status=active, health=ok`，系统回到 demo 基线。

## 第 1 组：异常输入鲁棒

| 用例 | 实际 HTTP | 结果 |
|---|---:|---|
| 空 query | 422 | PASS |
| 超长 query 约 60KB | 200 | PASS，能处理 |
| 超大 JSON body 约 1MB query | 200 | PASS，能处理 |
| 非法 UTF-8 | 422 | PASS |
| 超深嵌套 JSON | 422 | PASS |
| 错误 Content-Type `text/plain` | 422 | PASS |
| 非法 UUID agent_id | 422 | PASS |
| 非法 UUID kb_id | 422 | PASS |
| 非法 UUID tool_id | 422 | PASS |

结论：异常输入未复现 500 或 hang。超长/超大 query 被正常处理；真实网关层 body size 限制未在本步验证。

## 第 2 组：依赖故障注入

每个依赖均按“stop -> 测试 -> start/wait”执行，最后又统一恢复。

| 故障 | 测试接口 | 实际 | 是否 hang | 结论 |
|---|---|---|---|---|
| Redis stop | `/auth/login` | 200 | 否 | 登录不依赖 Redis，PASS |
| Redis stop | backend agent run | 400 `provider_call_failed:ConnectionError`，耗时 14.455s | 否 | 有明确错误，但耗时偏长 |
| Redis stop | MaaS `/v1/chat/completions` | 500 `Internal Server Error` | 否 | FAIL，MaaS Redis 故障未结构化处理 |
| MinIO stop | 上传文档 | 500 `Internal Server Error`，耗时 6.152s | 否 | FAIL，上传存储故障未结构化处理 |
| MinIO stop | KB retrieve | 409 `no_active_model_channel` | 否 | 受 embedding channel failed 影响，恢复后基线正常 |
| MaaS stop | backend agent run | 500 `Internal Server Error`，耗时 6.151s | 否 | FAIL，MaaS 不可用未转结构化错误 |
| MaaS stop | MaaS healthz | client 502/connection error | 否 | 预期服务不可达 |
| sandbox stop | code tool `/run` | HTTP 200，ToolRun `status=failed`，`sandbox_call_failed` | 否 | PASS，业务层结构化失败 |
| Postgres stop | `/agents` | 500 `Internal Server Error` | 否 | 可接受为 5xx，但不结构化 |
| Postgres stop | `/auth/me` | 500 `Internal Server Error` | 否 | 可接受为 5xx，但不结构化 |
| Postgres restore | `/auth/login` | 200 | 否 | 恢复成功 |

客户端响应未泄露 Python traceback，均为简短错误体或 `Internal Server Error`。服务端日志中 Postgres 故障有完整 SQLAlchemy/psycopg traceback，属于服务端日志证据，不是客户端泄露。

额外发现：

- 依赖故障会把 MaaS model channel 标记为 failed；容器恢复后 channel health 不会自动恢复为 ok。
- 该状态污染导致后续普通 RAG 对话全部 `409 no_active_model_channel`，直到手动恢复 mock channel health。

## 第 3 组：SSE 中断与资源释放

| 用例 | 实际 |
|---|---|
| 单个 SSE 建连后立即断开 | 客户端关闭成功 |
| 5 个 SSE 并发建连后立即断开 | 客户端关闭成功 |
| 服务端日志 | 未从本轮截取到明确的 SSE 断开未捕获异常；日志尾部主要是 Postgres 故障 traceback |
| trace 收敛 | 立即断开场景未形成可稳定断言的 trace 结果 |

结论：本轮未观察到 SSE 断开导致服务不可用或明显僵尸连接；trace 收敛证据不足，建议后续用连接级监控或 ASGI lifespan 指标补测。

## 第 4 组：并发与竞态

第一次并发对话在依赖故障后、channel health 未恢复前执行：

| 用例 | 实际 |
|---|---|
| 并发 10 个普通对话 | 全部 409 `no_active_model_channel` |
| 原因 | `mock-embedding` channel health 被标记 failed |

恢复 mock channel 后补跑：

| 用例 | 实际 | 结论 |
|---|---|---|
| 并发 10 个普通对话 | 10/10 返回 200 | PASS |
| 并发 5 个同 KB 文档上传 | 5/5 返回 201 | PASS |
| 同一 conversation 并发续聊 5 个 | 5/5 返回 200 | PASS |
| 同一 conversation 最终消息数 | 12 | 基础一致性可接受；严格顺序需更细粒度断言 |

结论：基线恢复后基础并发未复现 500。故障后的 channel health 状态污染是更关键的可恢复性缺陷。

## 第 5 组：R4 真实流式超时

代码确认：

- `backend/app/orchestrator/runtime.py` 的 `call_maas_chat_stream` 使用 `httpx.AsyncClient(timeout=None)`。
- `maas/app/services.py` 的 `proxy_openai_stream` 使用 `httpx.AsyncClient(timeout=None)`。

demo 近似：

- 未执行稳定 hang 上游模拟。原因：需要可控慢上游/toxiproxy 或真实 provider 慢响应环境；直接用不可达地址更容易得到连接错误，不能证明“已连接但不返回”的永久挂起。

结论：**R4 代码层成立，真实运行风险待真 key/慢上游/toxiproxy 补测。** 当前实现没有上游流式首包/读超时，存在连接长期占用风险。

## 缺陷清单

| 编号 | 严重度 | 状态 | 证据 | 影响 |
|---|---|---|---|---|
| ROB-REDIS | P1/P2 | 已证实 | Redis stop 时 MaaS `/v1/chat/completions` 返回 500 | Redis 故障未结构化处理；MaaS 可用性受影响 |
| ROB-MINIO | P1/P2 | 已证实 | MinIO stop 时文档上传返回 500 | 存储故障未结构化处理，用户体验差 |
| ROB-MAAS | P1 | 已证实 | MaaS stop 时 backend agent run 返回 500 | 模型服务不可用未优雅降级 |
| ROB-CHANNEL | P1 | 已证实 | 故障后 mock-embedding channel health 保持 failed，恢复容器后普通对话仍 409 | 依赖恢复后业务不可自动恢复，需要健康探测/自愈 |
| ROB-PG | P2 | 已证实 | Postgres stop 时接口返回 500，服务端日志 traceback | DB 故障不可避免 5xx，但可改善错误包装与告警 |
| R4 | P1/P2 | 代码确认 | backend 与 MaaS 流式 HTTP client `timeout=None` | 慢/挂上游可能导致流式连接长期占用 |

## Demo 已验 / 待补

demo 已验：

- 异常输入 4xx/合理处理。
- 依赖 stop/start 下的 HTTP 码、是否 hang、恢复情况。
- sandbox down 的 code tool 路径能结构化失败。
- 基础并发对话、并发上传、同 conversation 并发续聊。
- 故障后系统和 mock channel 恢复到 demo 基线。

待补：

- R4 真正慢上游/toxiproxy 场景。
- SSE 断开 trace 收敛的更精确指标。
- 网关层 body size、连接数、请求速率限制。

## Step 10 结论

系统对异常输入总体稳健；sandbox down 的工具路径也能结构化失败。依赖故障鲁棒性偏弱：Redis、MinIO、MaaS 故障均出现 500 或非结构化错误，且 MaaS channel health 在故障后不会自动恢复，导致容器恢复后业务仍不可用。

当前所有依赖已恢复，mock channel 已恢复，demo 基线已确认。可以进入 Step 11 汇总报告，但鲁棒性缺陷需要作为上线前风险重点汇总。
