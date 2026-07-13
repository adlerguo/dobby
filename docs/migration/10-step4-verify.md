# 10 Step 4：外部 API Key 调用已发布智能体验证

本步骤验证主线终点：

> 外部系统用 API Key 调用已发布智能体，走完整 RAG 问答，返回答案和引用。

本步不需要用户 JWT 调用 public 接口，只需要 Step3 生成的 App API Key。

## 0. 重建 backend

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend maas sandbox postgres redis minio
```

健康检查：

```bash
curl -s http://localhost:8001/healthz
```

期望：

- backend 返回 `status=ok`

## 1. 准备 JWT、APP_ID、APP_API_KEY

先拿内部管理用 JWT。这个 JWT 只用于启停 Key、查询列表和回归内部接口；public 调用不用它。

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

使用 Step3 已生成并记录下来的 app_id 和明文 key：

```bash
APP_ID='替换成Step3已发布应用ID'
APP_API_KEY='替换成Step3生成时只展示一次的sk-明文key'
```

如果你手上没有明文 key 了，重新生成一个：

```bash
APP_API_KEY=$(curl -s -X POST http://localhost:8001/api/v1/published-apps/$APP_ID/keys \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Step4 Test Key","scopes":["agent:invoke"]}' \
  | tee /tmp/step4-key-created.json \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["api_key"])')

KEY_ID=$(python3 -c 'import json; print(json.load(open("/tmp/step4-key-created.json"))["id"])')

echo "APP_API_KEY=$APP_API_KEY"
echo "KEY_ID=$KEY_ID"
```

如果你已有明文 key，但不知道 key_id，可从列表里取该 app 最新 key：

```bash
KEY_ID=$(curl -s http://localhost:8001/api/v1/published-apps/$APP_ID/keys \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); print(rows[0]["id"])')

echo "KEY_ID=$KEY_ID"
```

## 2. 有效 Key 调用 public chat

```bash
curl -s -X POST http://localhost:8001/api/v1/public/apps/$APP_ID/chat \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","stream":false}' \
  | tee /tmp/step4-public-chat-ok.json \
  | python3 -m json.tool
```

检查响应：

```bash
python3 - <<'PY'
import json
data=json.load(open("/tmp/step4-public-chat-ok.json"))
print("answer_preview=", data.get("answer","")[:160])
print("citation_count=", len(data.get("citations") or []))
print("conversation_id=", data.get("conversation_id"))
print("usage=", data.get("usage"))
assert data.get("answer"), "answer is empty"
assert data.get("conversation_id"), "conversation_id is empty"
assert data.get("citations"), "citations is empty"
first=(data.get("citations") or [{}])[0]
assert first.get("doc_name"), "citation.doc_name is empty"
assert first.get("snippet"), "citation.snippet is empty"
PY
```

期望：

- 有 `answer`
- 有 `conversation_id`
- `citations` 非空，包含 `doc_name/snippet/score`
- 回答应基于 Step1/2 的知识库内容

## 3. 安全验证 A：不带 Authorization

```bash
curl -s -o /tmp/step4-no-auth.json -w "%{http_code}\n" \
  -X POST http://localhost:8001/api/v1/public/apps/$APP_ID/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？"}'

cat /tmp/step4-no-auth.json | python3 -m json.tool
```

期望：

- HTTP 状态码 `401`
- detail 为 `invalid_credentials`

## 4. 安全验证 B：乱编假 Key

```bash
curl -s -o /tmp/step4-fake-key.json -w "%{http_code}\n" \
  -X POST http://localhost:8001/api/v1/public/apps/$APP_ID/chat \
  -H "Authorization: Bearer sk-fake-invalid-key" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？"}'

cat /tmp/step4-fake-key.json | python3 -m json.tool
```

期望：

- HTTP 状态码 `401`
- detail 为 `invalid_credentials`

## 5. 安全验证 C：停用 Key 后不可调用

停用：

```bash
curl -s -X POST http://localhost:8001/api/v1/published-apps/$APP_ID/keys/$KEY_ID/status \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"status":"disabled"}' \
  | python3 -m json.tool
```

调用：

```bash
curl -s -o /tmp/step4-disabled-key.json -w "%{http_code}\n" \
  -X POST http://localhost:8001/api/v1/public/apps/$APP_ID/chat \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？"}'

cat /tmp/step4-disabled-key.json | python3 -m json.tool
```

期望：

- HTTP 状态码 `401`
- detail 为 `invalid_credentials`
- 不区分“Key 不存在”和“Key 停用”，避免泄露内部状态

恢复 active，供后续验证：

```bash
curl -s -X POST http://localhost:8001/api/v1/published-apps/$APP_ID/keys/$KEY_ID/status \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"status":"active"}' \
  | python3 -m json.tool
```

## 6. 安全验证 D：用 A 应用 Key 调 B 应用

创建另一个 published app，用于跨 app 测试。先取当前 app 对应 agent：

```bash
AGENT_ID=$(curl -s http://localhost:8001/api/v1/published-apps/$APP_ID \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["agent_id"])')

OTHER_APP_ID=$(curl -s -X POST http://localhost:8001/api/v1/published-apps \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$AGENT_ID\",\"name\":\"Step4 Other App $(date +%s)\",\"publish_type\":\"api\",\"config\":{}}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "OTHER_APP_ID=$OTHER_APP_ID"
```

用 `$APP_API_KEY` 调 `$OTHER_APP_ID`：

```bash
curl -s -o /tmp/step4-wrong-app.json -w "%{http_code}\n" \
  -X POST http://localhost:8001/api/v1/public/apps/$OTHER_APP_ID/chat \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？"}'

cat /tmp/step4-wrong-app.json | python3 -m json.tool
```

期望：

- HTTP 状态码 `403`
- detail 为 `app_forbidden`
- A 应用 Key 不能调用 B 应用

## 7. 安全验证 E：应用下线后不可调用

下线原应用：

```bash
curl -s -X POST http://localhost:8001/api/v1/published-apps/$APP_ID/unpublish \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

再次调用原应用：

```bash
curl -s -o /tmp/step4-unpublished-app.json -w "%{http_code}\n" \
  -X POST http://localhost:8001/api/v1/public/apps/$APP_ID/chat \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？"}'

cat /tmp/step4-unpublished-app.json | python3 -m json.tool
```

期望：

- HTTP 状态码 `403`
- detail 为 `app_unavailable`

注意：当前 Step3 只实现了下线，没有“重新上线”接口。完成这个验证后，如果你还需要一个 active app 继续做 Step4 后续测试，请按第 1 节重新发布一个 app 并生成新 key。

## 8. last_used_at 更新验证

如果第 7 步已经把原 app 下线，请使用第 1 节重新发布 app 并生成一个新的 active key，然后设置：

```bash
APP_ID='新的active app id'
APP_API_KEY='新的sk明文key'
KEY_ID='新的key id'
```

先看调用前：

```bash
curl -s http://localhost:8001/api/v1/published-apps/$APP_ID/keys \
  -H "Authorization: Bearer $ACCESS" \
  | tee /tmp/step4-keys-before.json \
  | python3 -m json.tool
```

成功调用一次：

```bash
curl -s -X POST http://localhost:8001/api/v1/public/apps/$APP_ID/chat \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？"}' \
  | python3 -m json.tool
```

再看调用后：

```bash
curl -s http://localhost:8001/api/v1/published-apps/$APP_ID/keys \
  -H "Authorization: Bearer $ACCESS" \
  | tee /tmp/step4-keys-after.json \
  | python3 -m json.tool
```

检查：

```bash
KEY_ID="$KEY_ID" python3 - <<'PY'
import json, os
key_id=os.environ.get("KEY_ID")
before=json.load(open("/tmp/step4-keys-before.json"))
after=json.load(open("/tmp/step4-keys-after.json"))
def find(rows):
    return next(x for x in rows if not key_id or x["id"] == key_id)
b=find(before)
a=find(after)
print("before_last_used_at=", b.get("last_used_at"))
print("after_last_used_at=", a.get("last_used_at"))
assert a.get("last_used_at"), "last_used_at was not updated"
PY
```

期望：

- 成功调用后 `last_used_at` 有值，且晚于调用前。

## 9. 回归：内部 JWT /chat 仍正常

取一个 active agent：

```bash
AGENT_ID=$(curl -s http://localhost:8001/api/v1/agents \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); print(next(x["id"] for x in rows if x["status"]=="active"))')

curl -N -s -X POST http://localhost:8001/api/v1/chat \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$AGENT_ID\",\"query\":\"合同审批要注意什么？\",\"max_tool_rounds\":0}" \
  | tee /tmp/step4-internal-chat.sse

grep -n "event: citation" /tmp/step4-internal-chat.sse
grep -n "event: done" /tmp/step4-internal-chat.sse
```

期望：

- 内部 JWT `/chat` 仍返回 `citation` 和 `done`
- 没有被 API Key 鉴权影响

## 10. 本步新增接口

```text
POST /api/v1/public/apps/{app_id}/chat
```

请求示例：

```json
{
  "query": "合同审批要注意什么？",
  "conversation_id": null,
  "stream": false
}
```

响应示例：

```json
{
  "answer": "...",
  "citations": [
    {"doc_name": "...", "snippet": "...", "score": 0.032}
  ],
  "conversation_id": "...",
  "usage": {}
}
```

本步只支持非流式调用。`stream=true` 会返回 `400 stream_not_supported`，SSE 外部调用留后续批次。
