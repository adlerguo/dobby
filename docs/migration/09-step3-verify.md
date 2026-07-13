# 09 Step 3：发布应用与 API Key 验证

本步骤验证：

1. 新增 `published_apps` 和 `app_api_keys` 两张表。
2. 能把一个 active 智能体发布为 API 应用。
3. 能生成 API Key，明文只在生成响应里出现一次。
4. Key 列表只返回 `key_prefix/status/created_at` 等安全字段，不返回明文和 hash。
5. 发布中心前端能完成发布、生成 Key、查看 Key、启停 Key。

Step 4 的“外部用 Key 调用智能体”不在本步。

## 0. 重建并迁移

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend maas sandbox postgres redis minio
docker compose exec backend alembic upgrade head
```

确认新表：

```bash
docker compose exec postgres psql -U app -d eap -c '\d published_apps'
docker compose exec postgres psql -U app -d eap -c '\d app_api_keys'
```

期望：

- `published_apps` 有 `tenant_id/agent_id/name/status/publish_type/config/created_by/created_at/updated_at`
- `app_api_keys` 有 `tenant_id/app_id/name/key_hash/key_prefix/scopes/status/expires_at/created_by/created_at/last_used_at`

## 1. 登录拿 Token

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8001/api/v1/auth/me \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：能返回当前用户，具备 `agent:publish` 权限或 `super_admin` 角色。

## 2. 选择 Step2 已验证通过的 active 智能体

推荐用 Step2 前端新建并验证 RAG 的那个智能体。按名称精确匹配：

```bash
AGENT_NAME='替换成Step2已验证通过的智能体名称'

AGENT_ID=$(curl -s http://localhost:8001/api/v1/agents \
  -H "Authorization: Bearer $ACCESS" \
  | AGENT_NAME="$AGENT_NAME" python3 -c 'import os,sys,json; rows=json.load(sys.stdin); name=os.environ["AGENT_NAME"]; matches=[x for x in rows if x["name"]==name]; assert len(matches)==1, f"expected exactly one agent named {name}, got {len(matches)}"; print(matches[0]["id"])')

echo "AGENT_ID=$AGENT_ID"
```

如果它还不是 active，先发布智能体：

```bash
curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/publish \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

确认：

```bash
curl -s http://localhost:8001/api/v1/agents/$AGENT_ID \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：

- `status=active`
- `kb_ids` 非空
- `config.rag` 存在

## 3. 发布成 API 应用

```bash
APP_ID=$(curl -s -X POST http://localhost:8001/api/v1/published-apps \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$AGENT_ID\",\"name\":\"Step3 API App $(date +%s)\",\"publish_type\":\"api\",\"config\":{}}" \
  | tee /tmp/step3-app.json \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "APP_ID=$APP_ID"
cat /tmp/step3-app.json | python3 -m json.tool
```

期望：

- 返回 `id`
- `agent_id=$AGENT_ID`
- `status=published`
- `publish_type=api`

查询列表和详情：

```bash
curl -s http://localhost:8001/api/v1/published-apps \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool

curl -s http://localhost:8001/api/v1/published-apps/$APP_ID \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

## 4. 生成 API Key，明文只出现一次

```bash
curl -s -X POST http://localhost:8001/api/v1/published-apps/$APP_ID/keys \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Step3 Test Key","scopes":["agent:invoke"]}' \
  | tee /tmp/step3-key-created.json \
  | python3 -m json.tool
```

保存一次性明文 Key：

```bash
APP_API_KEY=$(python3 -c 'import json; print(json.load(open("/tmp/step3-key-created.json"))["api_key"])')
KEY_ID=$(python3 -c 'import json; print(json.load(open("/tmp/step3-key-created.json"))["id"])')

echo "KEY_ID=$KEY_ID"
echo "APP_API_KEY=$APP_API_KEY"
```

期望：

- 生成响应里有 `api_key`，形如 `sk-...`
- 生成响应里有 `key_prefix`
- 生成响应里没有 `key_hash`

安全检查：

```bash
grep -o 'key_hash' /tmp/step3-key-created.json || echo 'no key_hash in create response'
```

期望输出：

```text
no key_hash in create response
```

## 5. Key 列表不得泄漏明文或 hash

```bash
curl -s http://localhost:8001/api/v1/published-apps/$APP_ID/keys \
  -H "Authorization: Bearer $ACCESS" \
  | tee /tmp/step3-key-list.json \
  | python3 -m json.tool
```

检查无明文、无 hash：

```bash
python3 - <<'PY'
import json, os
created=json.load(open("/tmp/step3-key-created.json"))
rows=json.load(open("/tmp/step3-key-list.json"))
raw=created["api_key"]
text=open("/tmp/step3-key-list.json").read()
print("key_count=", len(rows))
print("first_key_prefix=", rows[0].get("key_prefix") if rows else "")
assert rows, "key list is empty"
assert "key_hash" not in text, "key_hash leaked"
assert raw not in text, "raw api key leaked"
assert "api_key" not in text, "api_key field leaked in list"
PY
```

期望：

- `key_count >= 1`
- 只看到 `key_prefix`
- 不出现 `key_hash`
- 不出现完整 `APP_API_KEY`
- 不出现 `api_key` 字段

## 6. 停用 Key

```bash
curl -s -X POST http://localhost:8001/api/v1/published-apps/$APP_ID/keys/$KEY_ID/status \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"status":"disabled"}' \
  | tee /tmp/step3-key-disabled.json \
  | python3 -m json.tool
```

确认状态：

```bash
python3 - <<'PY'
import json
data=json.load(open("/tmp/step3-key-disabled.json"))
print("status=", data.get("status"))
assert data.get("status") == "disabled", "key status is not disabled"
assert "key_hash" not in open("/tmp/step3-key-disabled.json").read(), "key_hash leaked"
assert "api_key" not in open("/tmp/step3-key-disabled.json").read(), "api_key leaked"
PY
```

重新启用，给 Step4 预留：

```bash
curl -s -X POST http://localhost:8001/api/v1/published-apps/$APP_ID/keys/$KEY_ID/status \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"status":"active"}' \
  | python3 -m json.tool
```

## 7. ⚠️需手动操作：浏览器发布中心验证

打开：

```text
http://localhost:18080/publish
```

强制刷新：

```text
Cmd + Shift + R
```

手动操作：

1. 选择 Step2 已验证的 active 智能体。
2. 点击“发布为 API”。
3. 在“已发布应用”列表看到新增应用。
4. 点击该应用的“生成 Key”。
5. 在弹窗里点击“生成”。
6. 确认弹窗出现完整 `sk-...` 明文 Key。
7. 复制或记录该 Key。
8. 关闭弹窗。
9. 在“API Key 列表”里确认只能看到 `key_prefix`，看不到完整明文。
10. 点击“停用”，确认状态变成 `disabled`。
11. 点击“启用”，确认状态变回 `active`。

期望：

- 明文 Key 只在生成弹窗出现一次。
- 列表永远只显示 `key_prefix`。
- 浏览器页面不展示 `key_hash`。

## 8. 回归 Step1/Step2 RAG 链路

选择同一个 agent，验证 context 仍能注入知识：

```bash
curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/context \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","max_tokens":3500}' \
  | tee /tmp/step3-context.json \
  | python3 -m json.tool

python3 - <<'PY'
import json
data=json.load(open("/tmp/step3-context.json"))
chunks=data.get("retrieved_chunks") or []
messages="\n".join(m.get("content","") for m in data.get("messages", []))
print("retrieved_chunks=", len(chunks))
print("has_knowledge_message=", "知识片段" in messages)
assert chunks, "retrieved_chunks is empty"
assert "知识片段" in messages, "knowledge was not injected"
PY
```

验证 SSE 仍有 citation：

```bash
curl -N -s -X POST http://localhost:8001/api/v1/chat \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$AGENT_ID\",\"query\":\"合同审批要注意什么？\",\"max_tool_rounds\":0}" \
  | tee /tmp/step3-chat.sse

grep -n "event: citation" /tmp/step3-chat.sse
grep -n "event: done" /tmp/step3-chat.sse
```

期望：

- context 有 `retrieved_chunks`
- messages 有 “知识片段”
- SSE 有 `citation` 和 `done`

## 9. 本步新增接口汇总

```text
POST /api/v1/published-apps
GET  /api/v1/published-apps
GET  /api/v1/published-apps/{app_id}
POST /api/v1/published-apps/{app_id}/unpublish
POST /api/v1/published-apps/{app_id}/keys
GET  /api/v1/published-apps/{app_id}/keys
POST /api/v1/published-apps/{app_id}/keys/{key_id}/status
```

安全约束：

- `POST /keys` 的响应包含一次性 `api_key`。
- `GET /keys` 和 `POST /keys/{key_id}/status` 绝不返回 `api_key` 或 `key_hash`。
- 数据库存储只保存 `key_hash` 和 `key_prefix`，不保存明文。
