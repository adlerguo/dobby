# Step 9 可观测、审计、用量、仪表盘与评测测试记录

- 测试时间戳：`1784007304`
- git HEAD：`aeb7bd5e4a8e4d30783eb4648df4e93f85483728`
- MaaS `PRODUCTION_MODE`：`false`
- 测试脚本：`qa/scripts/step9_observability_runner.py`
- 原始结果：`qa/env/step9-results.json`
- 摘要输出：`qa/env/step9-runner-output.md`

## Fixture

| 项 | 值 |
|---|---|
| 租户 A | `qa-a-1784000862` / `87ae1a50-9249-4ee0-a69d-bb1600914927` |
| 租户 B | `qa-b-1784002756` / `c13bd06a-96c1-4a65-a7c3-3ed7028f3085` |
| alice | `alice-1784002756`，builder |
| bob | `bob-1784002756`，builder |
| no-dashboard 用户 | `step9-nodash-1784007304`，无角色 |
| A agent | `87e36114-9032-4907-ac66-1f689fc1e872` |
| B agent | `aea212aa-56c3-46fc-ba73-ab2410f04032` |

## 代码证据

- `backend/app/orchestrator/runtime.py:80-103`：普通非流式运行创建 agent root trace，初始 `status=running`。
- `backend/app/orchestrator/runtime.py:153-163`：成功后 root trace 写入 `status=ok`、answer、usage、citations、tokens、latency 并 commit。
- `backend/app/orchestrator/runtime.py:437-473`：model span 记录 parent_id、input/output、tokens、latency；HTTPError 时设置 model trace `status=failed` 后抛 `ValueError`，但上层非流式路径没有显式 commit failed trace。
- `backend/app/services/audit_service.py:23-37`：审计写入 tenant_id、user_id、action、resource_type、resource_id、ip、detail。
- `backend/app/services/audit_service.py:52-65`：审计查询按 `AuditLog.tenant_id == tenant_id` 过滤。
- `backend/app/api/v1/audit.py:15-27`：审计查询接口需要 `audit:view`。
- `backend/app/api/v1/dashboard.py:19-44`：dashboard 需要 `dashboard:view`，并按当前 tenant_id 聚合。
- `backend/app/services/eval_service.py:80-155`：评测逐 case 调用 agent，写 `EvalRun.detail`，可选择写经验。

## 第 1 组：问答日志 / RunTrace

### 正常对话与续聊

| 用例 | 实际 | 结论 |
|---|---|---|
| alice 第 1 轮不带工具对话 | HTTP `200` | PASS |
| alice 带 `conversation_id` 续聊 | HTTP `200` | PASS |
| A conversation messages | 4 条：user/assistant/user/assistant | PASS |
| assistant citations | 每条 assistant message `citations_count=1` | PASS |
| bob 访问 A messages | `404 conversation_not_found` | PASS |
| alice 查 A trace detail | `200` | PASS |
| bob 查 A trace detail | `404 trace_not_found` | PASS |

Trace detail 摘要：

| span | parent | status | tokens | latency_ms | 结构 |
|---|---|---|---:|---:|---|
| agent `run_agent` | `null` | `ok` | 56 | 9 | input 含 query/model/context；output 含 answer/usage/citations/tool_results |
| model `maas_chat` | agent trace id | `ok` | 56 | 8 | input 含 model/message_count；output 含 finish_reason/usage |
| agent `run_agent` 续聊 | `null` | `ok` | 68 | 9 | context.truncation.history_requested=2 |
| model `maas_chat` 续聊 | agent trace id | `ok` | 68 | 8 | parent 关系正确 |

`/traces/{trace_id}` 返回：

- `summary.span_count=4`
- `summary.message_count=4`
- `summary.total_tokens=248`
- `summary.has_tool_call=false`
- `summary.has_error=false`

结论：**正常对话和续聊的 RunTrace 树、parent 关系、messages/citations 落库完整，租户隔离有效。**

### 失败对话

构造：创建一个没有 MaaS channel 的 LLM model，并绑定到 active agent 后运行。

| 项 | 实际 |
|---|---|
| API 响应 | `409 no_active_model_channel` |
| failure agent 下 RunTrace | 0 条 |
| 期望 | 至少有 root/model trace，`status=failed`，output 记录错误 |

结论：**FAIL。非流式失败对话没有持久化 failed RunTrace。** 代码里 model span 在异常时设置 `status=failed` 后抛错，但非流式上层没有 commit，实际 DB 查不到失败 trace。这会影响失败率、错误审计和排障可见性。

## 第 2 组：审计日志

触发动作：

- `auth.login`
- `tool.create`
- `tool.update`
- `tool.disable`
- `published_app.create`
- `eval_case.create`
- `agent.eval`

DB 审计记录样例：

| action | resource_type | tenant_id | user_id | ip | detail |
|---|---|---|---|---|---|
| `tool.create` | `tool` | A | alice | `192.168.65.1` | name/type |
| `tool.update` | `tool` | A | alice | `192.168.65.1` | fields |
| `tool.disable` | `tool` | A | alice | `192.168.65.1` | `{}` |
| `published_app.create` | `published_app` | A | alice | `192.168.65.1` | agent_id/publish_type |
| `eval_case.create` | `eval_case` | A | alice | `192.168.65.1` | scene/assert_type |
| `agent.eval` | `agent` | A | alice | `192.168.65.1` | total/passed/failed/pass_rate |
| `auth.login` | `auth` | A/B | alice/bob | `192.168.65.1` | username/tenant_code |

隔离证据：

- DB 计数：A audit_logs=`102`，B audit_logs=`14`，记录均带各自 tenant_id。
- 审计服务查询逻辑按 tenant_id 过滤。
- API 侧 alice/bob 查询 `/audit-logs` 均返回 `403 permission_denied`，因为当前 builder 角色没有 `audit:view`。

结论：**审计写入字段完整、DB 层 tenant_id 隔离成立；但本环境缺少具备 `audit:view` 的 A/B 测试用户，无法通过普通 API 验证“alice 只能看 A 审计”。** 当前 API 对 builder 返回 403 符合权限配置。

## 第 3 组：用量统计

DB usage_records 样例：

| tenant | prompt | completion | latency_ms | cost | cache_hit | 备注 |
|---|---:|---:|---:|---:|---|---|
| A | 45 | 3 | `null` | `null` | false | public app path 写入 |
| A | 42 | 6 | 0 | 0.0 | false | MaaS mock usage |
| A | 2728 | 2702 | 9 | 0.0 | false | mock usage |
| B | 有记录 | 有记录 | 有记录 | 0.0 | false | 租户 B 分开记录 |

隔离证据：

- A usage_records count=`151`
- B usage_records count=`1`
- 查询按 tenant_id 可区分，未观察到 A/B 混写。

R10 结论：

- **R10 成立/延续：未见真实成本计算。** MaaS mock 路径 cost 为 `0.0`；public app 额外记录 cost 为 `null`。demo 下 token/latency/cache_hit 结构可验，但 cost 不是可用真实成本。

## 第 4 组：仪表盘聚合

| 用例 | 实际 | 结论 |
|---|---|---|
| alice `/dashboard/executive` | `200` | PASS |
| bob `/dashboard/executive` | `200` | PASS |
| no-role 用户 `/dashboard/executive` | `403 permission_denied` | PASS |

隔离证据：

| 租户 | service_count | success_rate | active_agents | adoption |
|---|---:|---:|---:|---|
| A | 14 | 85.71% | 11 | 仅 A agent 列表 |
| B | 2 | 100.0% | 1 | 仅 B agent `QA B-1784002756 Agent` |

结论：dashboard 结构完整，权限控制生效，A/B 聚合结果分离。真实业务数值准确性仍需真 key/真实流量补测。

## 第 5 组：评测

| 用例 | 实际 | 结论 |
|---|---|---|
| 创建 eval case | `201` | PASS |
| 运行 agent eval，`max_tool_rounds=0` | `200` | PASS |
| eval report | total=1, passed=1, failed=0, pass_rate=100.0 | PASS |
| eval run detail | answer、trace_id、conversation_id、citation_count、tool_count=0、score=1.0 | PASS |
| bob GET A eval case | `404 eval_case_not_found` | PASS |

结论：评测路由结构可用，tenant_id 隔离有效；本轮避开工具编排，未触发 Step 5b/5c P0。

## 缺陷与风险

| 编号 | 严重度 | 状态 | 证据 | 影响 |
|---|---|---|---|---|
| O11 | P1/P2 | 已证实 | no-channel agent run 返回 `409 no_active_model_channel`，但 failure agent 下 RunTrace 为 0 条 | 失败调用不可观测，dashboard 错误率/排障可能漏记 |
| R10 | P2 | 已知延续 | usage_records cost 为 `0.0` 或 `null` | 无真实成本核算 |
| O12 | P3 | 权限/测试覆盖限制 | `/audit-logs` 需要 `audit:view`，当前 builder/member 无该权限 | 普通租户审计查看无法在现有角色下通过 API 验证 |

## Demo 已验 / 待真 key

demo 已验：

- 正常 RunTrace 树、messages、citations、续聊历史结构。
- conversation/trace/eval 跨租户隔离。
- audit_logs DB 字段完整和 tenant_id 分离。
- dashboard 结构、权限和租户聚合。
- eval case/run/report 结构。

待真 key 补测：

- 真实 token 统计准确性。
- 真实 latency、失败率和上游错误分布。
- 真实成本 cost 计算。
- 真实业务数据下 dashboard 指标口径校验。

## Step 9 结论

可观测与运营面在**成功路径**上基本可靠：RunTrace 树、messages/citations、dashboard、eval、审计字段与租户隔离都有证据支撑。

主要问题是**失败路径不可观测**：非流式模型失败返回 409，但 failed RunTrace 未持久化。建议作为 Step 10 前的关键观测缺陷入账。测试流程可以进入 Step 10，但上线前需要修复或明确失败 trace 的持久化策略。
