# Step 2 Verify: Model Hub Backend APIs

本步骤验证新增的模型纳管接口：

- 老接口 `/api/v1/models` 保留只读兼容。
- 新接口 `/api/v1/model-hub/models` 负责 CRUD、启停、渠道概览。
- 所有响应不得包含 `api_key_enc` 或密钥明文。

## 0. 前置：重建 backend

本步骤改了 backend 代码，必须 `--build`：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

docker compose up -d postgres redis minio maas sandbox
docker compose up -d --build backend
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed
```

健康检查：

```bash
curl -s http://localhost:8001/healthz
curl -s http://localhost:8100/healthz
```

登录拿 token：

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo "$ACCESS" | cut -c 1-24
```

## 1. 列出现有模型

```bash
curl -s "http://localhost:8001/api/v1/model-hub/models?limit=100" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：

- 能看到现有模型。
- 每条包含新字段，例如 `display_name`、`description`、`is_active`、`provider_config`、`import_source`、`scope_type`、`created_at`、`updated_at`。
- `is_active` 默认是 `true`。
- `import_source` 默认是 `external`。
- 响应里不含 `api_key_enc`。

密钥泄露检查：

```bash
curl -s "http://localhost:8001/api/v1/model-hub/models?limit=100" \
  -H "Authorization: Bearer $ACCESS" \
  | grep -E 'api_key|api_key_enc|sk-' && echo "LEAK" || echo "no secret fields"
```

期望输出：

```text
no secret fields
```

## 2. 创建一个带默认 MaaS 渠道的模型

如果你之前创建过同名测试模型，先换一个名字，或进入第 6 步验证重名。

```bash
MODEL_ID=$(curl -s -X POST http://localhost:8001/api/v1/model-hub/models \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{
    "name":"model-hub-test",
    "provider":"mock",
    "type":"llm",
    "display_name":"模型纳管测试",
    "description":"Step 2 后端接口验证模型",
    "default_channel":{
      "base_url":"mock://local",
      "api_key":"mock-key",
      "weight":5,
      "status":"active"
    }
  }' \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(json.dumps(data, ensure_ascii=False, indent=2)); print(data["id"], file=sys.stderr)' 2>/tmp/model-hub-test-id)

MODEL_ID=$(cat /tmp/model-hub-test-id)
echo "$MODEL_ID"
```

期望：

- HTTP 成功，返回模型 JSON。
- 返回里不含 `api_key`、`api_key_enc`。
- `name` 是 `model-hub-test`，`display_name` 是 `模型纳管测试`。

如果要看 HTTP 状态码：

```bash
curl -i -s -X POST http://localhost:8001/api/v1/model-hub/models \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"model-hub-test-status-code","provider":"mock","type":"llm"}' \
  | head -20
```

期望为 `201 Created`。

## 3. 查询单个模型

```bash
curl -s "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望能查到刚创建的 `model-hub-test`。

## 4. 更新展示名和描述

```bash
curl -s -X PATCH "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"display_name":"模型纳管测试-已更新","description":"PATCH 验证通过"}' \
  | python3 -m json.tool
```

再次查询：

```bash
curl -s "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望 `display_name` 和 `description` 已变更。

## 5. 启停模型

停用：

```bash
curl -s -X POST "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID/status" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"is_active":false}' \
  | python3 -m json.tool
```

确认：

```bash
curl -s "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["is_active"])'
```

期望输出：

```text
False
```

恢复启用，方便后续联调：

```bash
curl -s -X POST "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID/status" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"is_active":true}' \
  | python3 -m json.tool
```

## 6. 重名校验

```bash
curl -i -s -X POST http://localhost:8001/api/v1/model-hub/models \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"model-hub-test","provider":"mock","type":"llm"}' \
  | head -30
```

期望：

- HTTP `409 Conflict`
- detail 为 `model_name_exists`

## 7. 渠道概览不泄露密钥

```bash
curl -s "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID/channels" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：

- 能看到 `base_url`、`weight`、`rpm_limit`、`status`、`health`、`created_at`。
- 不含 `api_key`、`api_key_enc`。

密钥泄露检查：

```bash
curl -s "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID/channels" \
  -H "Authorization: Bearer $ACCESS" \
  | grep -E 'api_key|api_key_enc|mock-key|sk-' && echo "LEAK" || echo "no secret fields"
```

期望输出：

```text
no secret fields
```

## 8. 回归老接口和 MaaS

老接口仍正常：

```bash
curl -s http://localhost:8001/api/v1/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：

- 正常返回。
- 结构仍是老的 `id/name/provider/type`。

MaaS 模型列表仍正常：

```bash
curl -s http://localhost:8100/v1/models | python3 -m json.tool
```

MaaS mock chat 仍正常：

```bash
curl -s -X POST http://localhost:8100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"model-hub-test","messages":[{"role":"user","content":"ping"}]}' \
  | python3 -m json.tool
```

期望返回 `mock response: ping`。

