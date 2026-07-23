# Step 6 工具安全边界测试记录

- 测试时间戳：`1784005599`
- git HEAD：`aeb7bd5e4a8e4d30783eb4648df4e93f85483728`
- MaaS `PRODUCTION_MODE`：`false`
- 执行方式：只通过正常 API 与测试 fixture 数据验证；业务代码只读；脚本与结果仅写入 `qa/`
- 原始结果：`qa/env/step6-results.json`
- Runner 摘要：`qa/env/step6-runner-output.md`

## Fixture

| 项 | 值 |
|---|---|
| 租户 A | `qa-a-1784000862` / `87ae1a50-9249-4ee0-a69d-bb1600914927` |
| alice | `alice-1784002756`，builder，permissions=`agent:publish,dashboard:view,kb:create` |
| step6 member | `step6-member-1784005599`，member，permissions=`dashboard:view` |
| code 工具 | `0f079503-a741-46c2-98ba-c6425e082ca8` |
| http 工具 | `2a62663d-90ef-48ed-8a8d-2c0d6c6ecc84` |
| nl2data 工具 | `c3e95109-1f57-4bec-8ddd-02a64226c796` |

## 代码证据

### 直接运行接口权限边界

- `backend/app/api/v1/tools.py:34-39`：创建工具需要 `require_perm("agent:publish")`。
- `backend/app/api/v1/tools.py:71-77`：更新工具需要 `require_perm("agent:publish")`。
- `backend/app/api/v1/tools.py:98-103`：禁用工具需要 `require_perm("agent:publish")`。
- `backend/app/api/v1/tools.py:119-126`：运行工具只依赖 `get_current_auth`，即任意已登录用户可调用自己租户内 active 工具的 `/run`。

### R1 code 工具开关路径不一致

- `backend/app/orchestrator/runtime.py:637-652`：agent 编排路径在调用 `run_tool()` 前执行 `is_code_tool(tool) and not is_code_tool_allowed(tool)`，会返回 `auto_code_tool_disabled`。
- `backend/app/services/tool_service.py:84-99`：直接 `run_tool()` 对 `tool.type == "code"` 直接调用 `run_code_tool()`，未检查 `ENABLE_AUTO_CODE_TOOLS` 或白名单。
- `backend/app/services/tool_service.py:128-143`：`run_code_tool()` 将输入 code 直接转发到 sandbox `/exec`。

### R2 HTTP 工具 SSRF 边界缺失

- `backend/app/services/tool_service.py:102-125`：`run_http_tool()` 从用户输入读取 `url`，直接用 `httpx.AsyncClient().request(...)` 发起请求，未见 allowlist、私网 IP/主机名过滤、scheme 限制或回环阻断。

### R7 SQL 校验实现

- `backend/app/services/tool_service.py:276-294`：`validate_select_sql()` 使用 `startswith("select ") / startswith("with ")`、分号检测、字符串黑名单和 `from/join` 正则提取表名。它能挡住本轮测试的多语句与越权表访问，但属于字符串/正则校验，存在兼容性与误杀问题。

## 第 1 组：R1 code 工具开关直连绕过

### 构造

- 创建 `type=code` 工具。
- 直接调用 `POST /api/v1/tools/{code_tool_id}/run`。
- 输入无害 Python：
  - 打印 `QA_R1_DIRECT_CODE_OK`
  - 只列出 sandbox 环境变量名称，不读取值。

### 结果

| 项 | 实际 |
|---|---|
| API HTTP 状态 | `200` |
| ToolRun 状态 | `ok` |
| sandbox exit_code | `0` |
| stdout | `QA_R1_DIRECT_CODE_OK`，并输出 `ENV_NAMES=CPU_SECONDS,GPG_KEY,HOME,HOSTNAME,LANG,MAX_CONCURRENCY,MAX_OPEN_FILES,MAX_PROCESSES` |
| 是否被 `auto_code_tool_disabled` 拦截 | 否 |

### 结论

**R1 成立，P0/P1 安全缺陷。** 在 `ENABLE_AUTO_CODE_TOOLS=false` 的默认配置下，agent 编排路径会尝试拦截 code 工具，但直接 `/tools/{id}/run` 没有同样校验，builder 可创建 code 工具并直达 sandbox 执行代码。实际危害受 sandbox 隔离能力约束，但产品级开关已被绕过。

## 第 2 组：R2 HTTP 工具 SSRF

### 构造

- 创建 `type=http` 工具。
- 通过 `/tools/{id}/run` 输入不同 Docker 内网/回环 URL。
- 每个请求设置短超时，仅做可达性与响应头/少量 body 观测。

### 结果矩阵

| 目标 URL | API 状态 | 工具输出 | 结论 |
|---|---:|---|---|
| `http://minio:9000` | 200 | 连接成功，MinIO 返回 `403` XML | 可探测内网对象存储 |
| `http://minio:9001` | 200 | 连接成功，MinIO Console 返回 `200` HTML | 可访问内网管理界面入口 |
| `http://maas:8100/admin/channels` | 200 | 连接成功，返回 `200` JSON，body 包含渠道列表、tenant_id、model、provider、base_url、status、health、embedding_dim 等 | **高危命中** |
| `http://postgres:5432` | 200 | `http_tool_failed: Server disconnected without sending a response.` | 能向数据库端口发起连接探测 |
| `http://sandbox:8200/healthz` | 200 | 返回 `{"service":"sandbox","status":"ok","version":"0.1.0"}` | 可访问 sandbox 内网服务 |
| `http://169.254.169.254/latest/meta-data/` | 200 | `http_tool_failed`，短超时/不可达 | 当前环境未读到云元数据，但未见代码层阻断 |
| `http://localhost:8001/healthz` | 200 | 返回 `{"service":"backend","status":"ok","version":"0.1.0"}` | 可回环访问 backend |

`maas:8100/admin/channels` 响应摘录：

```json
[{"id":"2003bceb-eb7f-4993-812e-a191a690a838","tenant_id":"87ae1a50-9249-4ee0-a69d-bb1600914927","model_id":"986b3777-a9fc-4f53-9712-6824d456bd76","model":"qa-step5-fail-1784004383","model_type":"llm","provider":"mock","base_url":"mock://local","weight":1,"rpm_limit":null,"status":"active","health":"ok","error":null,"embedding_dim":null}, ...]
```

### 结论

**R2 成立，P0 安全缺陷。** HTTP 工具无 host/私网过滤，租户内 builder 创建工具后可通过后端容器网络访问内网服务。特别是 `maas:8100/admin/channels` 可达并返回管理端渠道列表，这是明确 SSRF 内网数据读取风险。

## 第 3 组：R7 nl2data SQL 校验绕过

### 构造与结果

| 用例 | SQL 摘要 | 实际结果 | PASS/FAIL |
|---|---|---|---|
| 大小写 SELECT | `SeLeCt COUNT(*) AS c FROM work_orders` | 成功返回 `5000` | PASS |
| 注释拆分 SELECT | `select/**/count(*) from work_orders` | `invalid_sql: only_select_allowed` | PASS |
| 多语句 | `SELECT ...; SELECT 1` | `invalid_sql: multiple_statements_not_allowed` | PASS |
| CTE 合法表 | `WITH x AS (...) SELECT * FROM x` | `invalid_sql: table_not_allowed` | FAIL-兼容性 |
| 直接读 `sqlite_master` | `SELECT name FROM sqlite_master` | `invalid_sql: table_not_allowed` | PASS |
| 子查询读 `sqlite_master` | `... IN (SELECT name FROM sqlite_master)` | `invalid_sql: table_not_allowed` | PASS |
| JOIN 越权表 | `JOIN sqlite_master` | `invalid_sql: table_not_allowed` | PASS |
| PRAGMA | `PRAGMA table_info(...)` | `invalid_sql: only_select_allowed` | PASS |
| 行注释 | `SELECT COUNT(*) ... -- comment` | 成功返回 `5000` | PASS，注释未禁用但未越权 |
| 字符串字面量误杀 | `SELECT ' insert ' ...` | `invalid_sql: write_or_admin_statement_not_allowed` | FAIL-误杀 |

### 结论

**本轮未复现 R7 可实际绕过。** 多语句、非 SELECT、`sqlite_master` 直接/子查询/JOIN 都被拦截，未读到非 allowed_tables，也未执行写操作。

但实现仍有设计风险：

- 依赖字符串黑名单和正则表名提取，不是 SQL AST/数据库权限级隔离。
- 合法 CTE 被误判为 `table_not_allowed`，说明表解析不精确。
- 字符串字面量包含 `" insert "` 会被误杀，说明黑名单未理解 SQL 语义。

建议将 R7 当前状态从“已证实绕过”调整为“未复现绕过，但 SQL 校验脆弱，P2/P1 风险待专项 fuzz/AST 校验补测”。

## 第 4 组：工具 CRUD 与权限

| 用例 | 实际 | 结论 |
|---|---|---|
| alice list tools | `200` | PASS |
| alice get code tool | `200` | PASS |
| alice patch echo tool | `200` | PASS |
| alice delete/disable calculator tool | `204` | PASS |
| disabled calculator `/run` | `404 tool_not_found` | PASS |
| member create tool | `403 permission_denied` | PASS |

补充：`/tools/{id}/run` 只要求登录，不要求 `agent:publish`。这对普通 builtin/http 工具可能是产品设计，但对 `code/http` 高风险类型应有额外权限和策略校验。

## 第 5 组：agent 工具编排 P0 阻断确认

- 非流式 `/agents/{tool_agent_id}/run` 绑定工具触发：HTTP `500 Internal Server Error`。
- 与 Step 5b/5c 一致，已知原因是 agent 编排路径的 `ContextToolOut.config` 类型错配。
- 本步安全测试使用直接 `/tools/{id}/run`，不依赖编排成功路径。

## 缺陷清单

| 编号 | 严重度 | 状态 | 复现摘要 | 实际 | 期望 |
|---|---|---|---|---|---|
| R1 | P0/P1 | 已证实 | `ENABLE_AUTO_CODE_TOOLS=false` 时，builder 创建 code 工具并直接 `/tools/{id}/run` | sandbox 执行成功，返回 stdout | 直接运行路径也应拒绝，返回 `auto_code_tool_disabled` 或权限错误 |
| R2 | P0 | 已证实 | builder 创建 HTTP 工具，URL 指向 Docker 内网 | 可访问 MinIO、sandbox、backend；`maas:8100/admin/channels` 返回管理数据 | 默认拒绝私网/回环/链路本地/metadata 地址，或只允许明确 allowlist |
| R7 | P2/P1 | 未复现实际绕过；实现脆弱 | 多语句/越权表/PRAGMA 等被拦，CTE 和字符串字面量误判 | 未读到越权表；存在误杀与 SQL 语义解析不足 | 使用 AST/数据库只读账号/视图 allowlist 等强约束 |
| P0-agent-tools | P0 | 已知仍存在 | `/agents/{id}/run` 触发工具 | HTTP 500 | 不应 500；应完成工具编排或返回结构化错误 |

## 修复建议方向（仅记录，不实施）

- R1：把 `is_code_tool_allowed` 或等价策略下沉到 `tool_service.run_tool()`，确保 agent 编排和直接 `/tools/{id}/run` 一致；对 code 工具增加独立权限点与审计。
- R2：HTTP 工具执行前做 URL 规范化和 DNS/IP 解析，拒绝 localhost、RFC1918、link-local、Docker 内网服务名、metadata 地址；生产环境使用租户级 allowlist。
- R7：避免字符串黑名单作为唯一防线；使用 SQL AST parser、只读连接、数据库视图/表 allowlist、禁止注释和多语句，并增加 fuzz 用例。
- Agent 工具 P0：修复 `ContextToolOut` 与 ORM `Tool` 类型错配，并保证异常转结构化 error，不直接 500/断流。

## Step 6 结论

工具安全边界当前**不可靠**：

- code 工具开关可被直接 `/tools/{id}/run` 绕过。
- HTTP 工具存在明确 SSRF，且 MaaS 管理端渠道列表可被读取。
- nl2data 本轮未打穿，但校验实现不够稳健，建议继续作为安全风险跟踪。

是否进入 Step 7：从测试流程上可以继续，但从发布质量看，R1/R2 至少需要作为阻断级安全缺陷入账，尤其 R2 的 `maas/admin/channels` 可达应优先处理。
