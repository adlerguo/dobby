# Step 1 认证 / JWT / RBAC / 多租户隔离测试记录

执行时间：2026-07-14 12:19:23 +0800

## Fixtures

口令已写入 `qa/env/step1-fixtures.json`，本记录不展开口令。

| 对象 | ID / Code | 用户 | 角色流转 |
|---|---|---|---|
| 租户 A | `87ae1a50-9249-4ee0-a69d-bb1600914927` / `qa-a-1784000862` | `alice-1784002756` | builder 创建资源，member 验 RBAC，builder 验跨租户写隔离 |
| 租户 B | `c13bd06a-96c1-4a65-a7c3-3ed7028f3085` / `qa-b-1784002756` | `bob-1784002756` | builder 创建资源，member 验 RBAC，builder 验跨租户写隔离 |

| 租户 | KB | Agent | Tool | Conversation | Document |
|---|---|---|---|---|---|
| A | `dc42b1d4-c46f-49f0-b311-5f68febc6087` | `87e36114-9032-4907-ac66-1f689fc1e872` | `cd2fda70-d8ae-405a-b656-4f9b47fb3284` | `ac891429-ba49-43f2-83f7-aef80f8ccd35` | `e62e4239-764d-4fd7-b04f-a8b1f8a9c84a` |
| B | `2fbc515d-6a20-4692-a34f-58505e3f7378` | `aea212aa-56c3-46fc-ba73-ab2410f04032` | `14e3ea7d-fd1f-47a8-8270-1931c9c9815f` | `86da2055-ff8c-4bd4-93fb-7479518cb2d1` | `1168dc17-11c8-46c7-bc22-9fc6faa8e82b` |

## A. 认证基础

| 用例 | 状态码 | detail/摘要 | 结论 |
|---|---:|---|---:|
| A1 admin correct login | 200 | `access` | PASS |
| A1 alice correct login | 200 | `access` | PASS |
| A1 bob correct login | 200 | `access` | PASS |
| A2 wrong password | 401 | `invalid_credentials` | PASS |
| A2 missing user | 401 | `invalid_credentials` | PASS |
| A2 wrong tenant | 401 | `invalid_credentials` | PASS |
| A7 refresh token | 200 | `access` | PASS |
| A7 access as refresh | 401 | `invalid_refresh_token` | PASS |
| A7 garbage refresh | 401 | `invalid_refresh_token` | PASS |

## B. JWT 安全

| 用例 | 状态码 | detail/摘要 | 结论 |
|---|---:|---|---:|
| B bad signature byte | 401 | `invalid_token` | PASS |
| B payload changed without resign | 401 | `invalid_token` | PASS |
| B alg none | 401 | `invalid_token` | PASS |
| B missing signature segment | 401 | `invalid_token` | PASS |
| B typ non access | 401 | `invalid_token` | PASS |
| B expired exp | 401 | `invalid_token` | FAIL |
| B tenant mismatch | 401 | `tenant_mismatch` | PASS |
| B no Authorization | 401 | `not_authenticated` | PASS |

## C. 账号/租户状态

| 用例 | 状态码 | detail/摘要 | 结论 |
|---|---:|---|---:|
| C1 alice disabled old token | 401 | `inactive_identity` | PASS |
| C tenant B disabled old token | 401 | `inactive_identity` | PASS |

## D. RBAC 权限点

| 用例 | 状态码 | detail/摘要 | 结论 |
|---|---:|---|---:|
| D alice permissions | 200 | `dashboard:view` | PASS |
| D member patch own tool | 403 | `permission_denied` | PASS |
| D member publish own agent | 403 | `permission_denied` | PASS |
| D admin create+patch default tool | 200 | `updated` | PASS |

## E. 跨租户越权矩阵

| 方向 | 资源 | 操作 | 状态码 | detail | 泄露对方数据 | 改动 | 结论 |
|---|---|---|---:|---|---:|---:|---:|
| alice(builder)->B | kb | GET | 404 | `kb_not_found` | False | False | PASS |
| alice(builder)->B | kb | PATCH | 404 | `kb_not_found` | False | False | PASS |
| alice(builder)->B | kb | DELETE | 404 | `kb_not_found` | False | False | PASS |
| alice(builder)->B | agent | GET | 404 | `agent_not_found` | False | False | PASS |
| alice(builder)->B | agent | PATCH | 404 | `agent_not_found` | False | False | PASS |
| alice(builder)->B | agent | DELETE | 404 | `agent_not_found` | False | False | PASS |
| alice(builder)->B | tool | GET | 404 | `tool_not_found` | False | False | PASS |
| alice(builder)->B | tool | PATCH | 404 | `tool_not_found` | False | False | PASS |
| alice(builder)->B | tool | DELETE | 404 | `tool_not_found` | False | False | PASS |
| alice(builder)->B | tool | RUN | 404 | `tool_not_found` | False | False | PASS |
| alice(builder)->B | conversation | GET | 404 | `conversation_not_found` | False | False | PASS |
| alice(builder)->B | conversation | PATCH | 405 | `Method Not Allowed` | False | False | PASS |
| alice(builder)->B | conversation | DELETE | 405 | `Method Not Allowed` | False | False | PASS |
| alice(builder)->B | conversation_messages | GET | 404 | `conversation_not_found` | False | False | PASS |
| alice(builder)->B | chat | POST conversation_id | 200 | `event: error data: {"detail": "agent_not_found"}  ` | False | False | PASS |
| alice(builder)->B | document_chunks | GET | 404 | `document_not_found` | False | False | PASS |
| alice(builder)->B | chat | POST agent_id | 200 | `event: error data: {"detail": "agent_not_found"}  ` | False | False | PASS |
| bob(builder)->A | kb | GET | 404 | `kb_not_found` | False | False | PASS |
| bob(builder)->A | kb | PATCH | 404 | `kb_not_found` | False | False | PASS |
| bob(builder)->A | kb | DELETE | 404 | `kb_not_found` | False | False | PASS |
| bob(builder)->A | agent | GET | 404 | `agent_not_found` | False | False | PASS |
| bob(builder)->A | agent | PATCH | 404 | `agent_not_found` | False | False | PASS |
| bob(builder)->A | agent | DELETE | 404 | `agent_not_found` | False | False | PASS |
| bob(builder)->A | tool | GET | 404 | `tool_not_found` | False | False | PASS |
| bob(builder)->A | tool | PATCH | 404 | `tool_not_found` | False | False | PASS |
| bob(builder)->A | tool | DELETE | 404 | `tool_not_found` | False | False | PASS |
| bob(builder)->A | tool | RUN | 404 | `tool_not_found` | False | False | PASS |
| bob(builder)->A | conversation | GET | 404 | `conversation_not_found` | False | False | PASS |
| bob(builder)->A | conversation | PATCH | 405 | `Method Not Allowed` | False | False | PASS |
| bob(builder)->A | conversation | DELETE | 405 | `Method Not Allowed` | False | False | PASS |
| bob(builder)->A | conversation_messages | GET | 404 | `conversation_not_found` | False | False | PASS |
| bob(builder)->A | chat | POST conversation_id | 200 | `event: error data: {"detail": "agent_not_found"}  ` | False | False | PASS |
| bob(builder)->A | document_chunks | GET | 404 | `document_not_found` | False | False | PASS |
| bob(builder)->A | chat | POST agent_id | 200 | `event: error data: {"detail": "agent_not_found"}  ` | False | False | PASS |

### 越权后 owner 回读校验

跨租户 PATCH/DELETE/RUN/CHAT 尝试后，使用资源所属租户 token 回读：

| 租户 | KB | Agent | Tool | Conversation | Document chunks | 结论 |
|---|---:|---:|---:|---:|---:|---:|
| A owner readback | 200 active | 200 active | 200 active | 200 | 200 | PASS |
| B owner readback | 200 active | 200 active | 200 active | 200 | 200 | PASS |

证据文件：`qa/env/step1-post-cross-owner-verify.json`。

## 缺陷清单

### P1/BLOCKER-QA：租户开通流程缺失

- 复现：`POST /api/v1/tenants` 创建新租户后，用 `default/admin` 调 `POST /api/v1/users` 创建用户。
- 实际：用户落在调用者 token 所属租户，无法指定新租户。
- 期望：提供租户初始化管理员、指定租户建用户接口，或明确租户开通流程。
- 影响：阻断纯 API 方式构造多租户 QA fixtures。

### P2：B expired exp

- 实际：status=401, detail=invalid_token
- 期望：401 且 detail 符合用例预期

### P2：跨租户 `/chat` 错误以 HTTP 200 SSE error 返回

- 复现：alice(builder) 使用 B 的 `agent_id` 或 `conversation_id` 调 `POST /api/v1/chat`；bob(builder) 对 A 对称执行。
- 实际：HTTP 状态码为 200，SSE body 中返回 `event: error` / `{"detail":"agent_not_found"}`；未泄露对方数据、未改动资源。
- 期望：按本步验收，越权访问应返回 404/403。若流式接口必须用 SSE error，也建议在接口契约中明确，否则客户端容易把 200 当成功。
- 严重度：P2，协议/客户端鲁棒性问题，不是 P0 越权。

## 结论

- 越权隔离是否守住：是。
- 认证/RBAC 基础：通过。
- JWT 安全：存在失败，见缺陷清单。
- 是否可以进入 Step 2：可以。
