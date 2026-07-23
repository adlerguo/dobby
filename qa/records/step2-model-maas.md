# Step 2 模型渠道 / MaaS 测试记录

执行时间：2026-07-14 12:29:44 +0800

## 第 1 组：连通性 probe

| 用例 | 结论 | 状态/摘要 |
|---|---:|---|
| P1 invalid protocol | PASS | `{"status": 200, "body": {"ok": false, "health": "failed", "error": "protocol_not_supported", "embedding_dim": null}}`  |
| P2 rerank unsupported | PASS | `{"status": 200, "body": {"ok": false, "health": "failed", "error": "model_type_not_supported", "embedding_dim": null}}`  |
| P3 mock probe | PASS | `{"status": 200, "body": {"ok": true, "health": "ok", "error": null, "embedding_dim": null}}`  |
| P4 invalid OpenAI key | PASS | `{"status": 200, "body": {"ok": false, "health": "failed", "error": "provider_http_401", "embedding_dim": null}}` 有效 key 待补测；本次验证无效 key/真实 base_url 路径 |

## 第 2 组：无候选与错误码

| 用例 | 结论 | 状态/摘要 |
|---|---:|---|
| E1 missing chat model | PASS | `{"status": 409, "body": {"detail": "no_active_model_channel"}}`  |
| E1 missing embedding model | PASS | `{"status": 409, "body": {"detail": "no_active_model_channel"}}`  |
| E2 existing model but no active channel | PASS | `{"status": 409, "body": {"detail": "no_active_model_channel"}}` disabled channel create status=201 |

## 第 3 组：RPM 限流

| 用例 | 结论 | 状态/摘要 |
|---|---:|---|
| RPM N+1 limited | PASS | `[{"status": 200, "body": {"id": "chatcmpl-mock-1784003377", "object": "chat.completion", "created": 1784003377, "model": "qa-step2-rpm-1784003377", "choices": [{"index": 0, "message": {"role": "assistant", "content": "mock response: rpm ...` redis_keys=['maas:rpm:8fe3fc93-dbbf-419d-a3b0-3205e366a1af:29733389'] |
| RPM redis key exists | PASS | `{"keys": ["maas:rpm:8fe3fc93-dbbf-419d-a3b0-3205e366a1af:29733389"], "values": {"maas:rpm:8fe3fc93-dbbf-419d-a3b0-3205e366a1af:29733389": "4"}}`  |

## 第 4 组：加权与故障转移

| 用例 | 结论 | 状态/摘要 |
|---|---:|---|
| Weighted cache-hit distribution favors high weight | PASS | `{"high_id": "cf6d5f72-377c-4326-a7cf-aafd7dc7d1de", "low_id": "6a00eb0f-07fc-4f95-bed7-320e2c9c94a0", "counts": {"6a00eb0f-07fc-4f95-bed7-320e2c9c94a0": 10, "cf6d5f72-377c-4326-a7cf-aafd7dc7d1de": 51}, "first_response": {"status": 200, "...`  |
| Failover bad primary to mock secondary | PASS | `{"response": {"status": 200, "body": {"id": "chatcmpl-mock-1784003379", "object": "chat.completion", "created": 1784003379, "model": "qa-step2-failover-1784003377", "choices": [{"index": 0, "message": {"role": "assistant", "content": "mo...`  |

## 第 5 组：生产模式过滤 mock

| 用例 | 结论 | 状态/摘要 |
|---|---:|---|
| Initial PRODUCTION_MODE false | PASS | `{"env": "false"}`  |
| Switch PRODUCTION_MODE true | PASS | `{"code": 0, "stdout": "", "stderr": " Container 6qiyeagent-redis-1  Running\n Container 6qiyeagent-postgres-1  Running\n Container 6qiyeagent-maas-1  Recreate\n Container 6qiyeagent-maas-1  Recreated\n Container 6qiyeagent-redis-1  Waiti...`  |
| Production filters mock chat | PASS | `{"status": 409, "body": {"detail": "no_active_model_channel"}}`  |
| Production filters mock embedding | PASS | `{"status": 409, "body": {"detail": "no_active_model_channel"}}`  |
| Restore PRODUCTION_MODE false | PASS | `{"code": 0, "stdout": "", "stderr": " Container 6qiyeagent-redis-1  Running\n Container 6qiyeagent-postgres-1  Running\n Container 6qiyeagent-maas-1  Recreate\n Container 6qiyeagent-maas-1  Recreated\n Container 6qiyeagent-postgres-1  Wa...`  |
| Demo mock restored | PASS | `{"status": 200, "body": {"id": "chatcmpl-mock-1784003362", "object": "chat.completion", "created": 1784003362, "model": "mock-chat", "choices": [{"index": 0, "message": {"role": "assistant", "content": "mock response: demo restored"}, "f...`  |

## 第 6 组：用量记录 / cost / cache

| 用例 | 结论 | 状态/摘要 |
|---|---:|---|
| Usage records written | PASS | `{"rows": [{"tenant_id": "87ae1a50-9249-4ee0-a69d-bb1600914927", "channel_id": "4c6c90ab-49ec-4d9e-a026-d515410ce01a", "prompt_tokens": "4", "completion_tokens": "6", "latency_ms": "0", "cost": "0.000000", "cache_hit": "f"}, {"tenant_id":...`  |
| Cost remains zero R10 | PASS | `{"rows": [{"tenant_id": "87ae1a50-9249-4ee0-a69d-bb1600914927", "channel_id": "4c6c90ab-49ec-4d9e-a026-d515410ce01a", "prompt_tokens": "4", "completion_tokens": "6", "latency_ms": "0", "cost": "0.000000", "cache_hit": "f"}, {"tenant_id":...`  |
| Chat cache hit on identical payload | PASS | `{"status": 200, "body": {"id": "chatcmpl-mock-1784003384", "object": "chat.completion", "created": 1784003384, "model": "qa-step2-usage-1784003377", "choices": [{"index": 0, "message": {"role": "assistant", "content": "mock response: sam...`  |
| Embedding cache hit on identical payload | PASS | `{"status": 200, "body": {"object": "list", "model": "qa-step2-usage-emb-1784003377", "data": [{"object": "embedding", "index": 0, "embedding": [0.8705882352941177, 0.21176470588235294, 0.050980392156862744, 0.3333333333333333, 0.75294117...`  |
| R11 cross-tenant cache risk observed structurally | PASS | `{"note": "MaaS /v1 endpoints do not accept tenant identity; candidate selection is global by model name. Two tenant-scoped channels for the same model were created, and identical payload produced cache_hit records without tenant in cache...` 缓存 key 只由 payload 构成，不含租户；MaaS 端点无租户身份 |

## Demo 已验 / 待真实 key 补测

- Demo 已验：mock probe、mock chat/embedding 路由、错误码、RPM、故障转移、生产模式过滤、usage/cache 结构。
- 待真实 key 补测：真实 openai_compatible 有效 key `ok=true`；本次已用无效 key验证真实 base_url 错误分类路径。

## 缺陷记录

- `usage` known: R10 cost remains zero -> `[{"tenant_id": "87ae1a50-9249-4ee0-a69d-bb1600914927", "channel_id": "4c6c90ab-49ec-4d9e-a026-d515410ce01a", "prompt_tokens": "4", "completion_tokens": "6", "latency_ms": "0", "cost": "0.000000", "cache_hit": "f"}, {"tenant_id": "87ae1a5...`
- `usage` risk: R11 cache key lacks tenant identity -> `{"note": "MaaS /v1 endpoints do not accept tenant identity; candidate selection is global by model name. Two tenant-scoped channels for the same model were created, and identical payload produced cache_hit records without tenant in cache...`

## 结论

- 生产模式过滤 mock：可靠。
- 模型路由/故障转移/RPM：通过 demo 验证。
- probe/错误码：通过 demo 验证。
- 是否可以进入 Step 3：可以。
