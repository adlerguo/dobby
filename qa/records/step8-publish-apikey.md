# Step 8 发布与 App API Key 测试记录

- 测试时间戳：`1784006585`
- git HEAD：`aeb7bd5e4a8e4d30783eb4648df4e93f85483728`
- MaaS `PRODUCTION_MODE`：`false`
- 测试脚本：`qa/scripts/step8_publish_apikey_runner.py`
- 原始结果：`qa/env/step8-results.json`
- 摘要输出：`qa/env/step8-runner-output.md`
- 公开端点实际路径：`POST /api/v1/public/apps/{app_id}/chat`

## Fixture

| 项 | 值 |
|---|---|
| 租户 A | `qa-a-1784000862` / `87ae1a50-9249-4ee0-a69d-bb1600914927` |
| 租户 B | `qa-b-1784002756` / `c13bd06a-96c1-4a65-a7c3-3ed7028f3085` |
| alice | `alice-1784002756`，builder |
| bob | `bob-1784002756`，builder |
| member | `step8-member-1784006585`，member |
| A agent | `87e36114-9032-4907-ac66-1f689fc1e872` |
| B agent | `aea212aa-56c3-46fc-ba73-ab2410f04032` |
| A published app | `2254c826-23ac-4673-87f1-66e156ead63d` |
| B published app | `93b4dd52-f6e1-493d-9f80-b62fcfd328d5` |

## 代码证据

### 发布与 key 创建

- `backend/app/api/v1/publish.py:39-47`：创建 published app 需要 `require_perm("agent:publish")`。
- `backend/app/api/v1/publish.py:105-139`：创建 app API key 需要 `require_perm("agent:publish")`，返回 `AppApiKeyCreatedOut(..., api_key=raw_key)`。
- `backend/app/api/v1/publish.py:142-151`：列表 key 使用 `AppApiKeyOut`，不包含 `api_key` 明文字段。
- `backend/app/services/publish_service.py:80-95`：生成 raw key 后仅存 `key_hash=sha256(raw_key)` 和 `key_prefix=mask_api_key(raw_key)`。
- `backend/app/models/entities.py:339-354`：`app_api_keys` 表包含 `key_hash/key_prefix/status/expires_at/last_used_at`，无明文字段。

### 公开端点鉴权与隔离

- `backend/app/core/api_key_auth.py:31-38`：无 Bearer、错误 key、非 active key、过期 key 均返回 `401 invalid_credentials`。
- `backend/app/core/api_key_auth.py:39-40`：key 绑定的 `app_id` 必须等于路径中的 `app_id`，否则 `403 app_forbidden`。
- `backend/app/core/api_key_auth.py:42-48`：app 必须存在、同租户、状态为 `published`；agent 必须存在、同租户、状态为 `active`，否则 `403 app_unavailable`。
- `backend/app/api/v1/public_agents.py:17-25`：公开 chat 不支持 stream，`stream=true` 返回 `400 stream_not_supported`。
- `backend/app/api/v1/public_agents.py:27-42`：公开 chat 固定使用 key 上下文中的 `tenant_id/agent_id`，且 `max_tool_rounds=0`。

## 第 1 组：发布流程与 key 存储

| 用例 | 实际 | 结论 |
|---|---|---|
| alice 发布 A agent 为 app | `201`，生成 A published app | PASS |
| bob 发布 B agent 为 app | `201`，生成 B published app | PASS |
| member 发布 A agent | `403` | PASS |
| 创建 A app key | `201`，响应含 `api_key` 明文 | PASS |
| 列表 A app keys | `200`，不含 `api_key` 字段 | PASS |
| DB 查询 key | 仅有 `key_hash/key_prefix`；`raw_key_equals_hash=false`；`hash_matches_one_raw_key=true` | PASS |

DB 证据摘要：

| key | tenant | app | status | 存储证据 |
|---|---|---|---|---|
| A key | A | A app | active | `key_hash=30a6...45c`，`key_prefix=sk-K4vHSnV****`，未存明文 |
| A revoke key | A | A app | disabled | `key_hash=e70c...411`，`key_prefix=sk-L4aDA3z****`，未存明文 |
| B key | B | B app | active | `key_hash=66f...527`，`key_prefix=sk-ODTDO8o****`，未存明文 |

结论：**key 明文仅创建时返回一次，列表与数据库未保存明文，存储为 SHA-256 hash + prefix。** 该项通过。

## 第 2 组：App API Key 校验

| 用例 | 实际 | 结论 |
|---|---|---|
| 正确 A key 调 A app 公开 chat | `200`，返回 `mock response: ping` | PASS |
| 伪造 key | `401 invalid_credentials` | PASS |
| 无 Authorization | `401 invalid_credentials` | PASS |
| A key 调 B app | `403 app_forbidden` | PASS |
| B key 调 A app | `403 app_forbidden` | PASS |
| disabled key 调 A app | `401 invalid_credentials` | PASS |
| B app unpublish 后 B key 调 B app | `403 app_unavailable` | PASS |

公开 chat 成功响应摘要：

```json
{
  "answer": "mock response: ping",
  "conversation_id": "7ab763f9-46a3-456c-a9f8-860ceae83360",
  "usage": {"prompt_tokens": 45, "completion_tokens": 3, "total_tokens": 48},
  "citations_count": 1
}
```

结论：key 与 app_id 绑定校验生效，错误/撤销/未发布 app 都会拒绝。

## 第 3 组：公开访问隔离

| 用例 | 实际 | 结论 |
|---|---|---|
| bob 管理端 GET A app | `404 published_app_not_found` | PASS |
| A key 访问 B app | `403 app_forbidden` | PASS |
| B key 访问 A app | `403 app_forbidden` | PASS |
| 创建 draft agent 后直接发布为 app | `400 agent_not_publishable` | PASS |
| 未发布 agent 公开访问 | 无公开 agent_id 入口；未发布 agent 无法创建 app，无法获得公开访问入口 | PASS |

结论：**公开 app 访问没有复现跨租户越权。** 公开 chat 的 agent/tenant 来自 key 绑定的 published app，而不是请求体可控字段；跨 app_id 使用 key 会被 `app_forbidden` 拒绝。

## 第 4 组：公开对话

| 用例 | 实际 | 结论 |
|---|---|---|
| A key 调 A app chat | `200`，返回 mock answer、citations、conversation_id、usage | PASS |
| `stream=true` | `400 stream_not_supported` | PASS |
| 工具编排影响 | 公开 chat 代码固定 `max_tool_rounds=0`，本轮未触发 Step 5b/5c 工具 P0 | PASS |
| 速率限制/配额 | 只读代码未见 public app key 级 rate limit/quota guard | RISK |

demo 已验：公开鉴权、租户绑定、mock LLM 链路、usage 结构。

待真 key 补测：真实模型回答质量、真实 token usage 准确性、生产配额/网关级限流策略。

## 缺陷与风险

| 编号 | 严重度 | 状态 | 证据 | 影响 |
|---|---|---|---|---|
| P8-RATE | P2 | 代码风险 | `public_agents.py` / `api_key_auth.py` 未见 app key 级速率限制或配额校验 | 公开 key 若泄露或被滥用，缺少应用层限流保护；是否由网关兜底需上线架构确认 |

未发现：

- App API Key 明文持久化。
- A/B 跨租户公开访问越权。
- 未发布 agent 可公开访问。
- disabled key 仍可用。

## Step 8 结论

发布、App API Key 存储与公开访问隔离在 demo 验证中总体可靠：

- key 明文只在创建时返回一次，DB 存 hash/prefix。
- key 与 app_id 强绑定，跨租户/跨 app 使用被拒。
- app unpublish 和 key disabled 后立即失效。
- 未发布 agent 不能被公开端点访问。

主要风险是公开端点未见应用层 rate limit/quota。可进入 Step 9，但建议把公开 API key 的限流/配额作为上线前风险项确认。
