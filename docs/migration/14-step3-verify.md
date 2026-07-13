# Step 3 验证：模型中心一键接入 + 连接测试

本步目标：用户从 `model_catalog` 目录项接入模型时，先由 MaaS 做临时连接测试，测试通过后才创建 `models/model_channels`。API Key 只传给 MaaS，MaaS 加密入库；backend 不落明文。

## 0. 启动与登录

本步改了 backend 和 maas，必须重新构建：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend maas postgres redis minio sandbox
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed_model_catalog
```

登录拿 token：

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

## 1. mock-chat 一键接入成功

取 `mock-chat` 目录项：

```bash
MOCK_CATALOG_ID=$(curl -s http://localhost:8001/api/v1/model-center/catalog \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; print(next(x["id"] for x in json.load(sys.stdin) if x["model_code"]=="mock-chat"))')

RUNTIME_NAME="mc-mock-$(date +%s)"

curl -s -X POST "http://localhost:8001/api/v1/model-center/catalog/$MOCK_CATALOG_ID/connect" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"runtime_name\":\"$RUNTIME_NAME\",\"api_key\":\"mock-key\",\"weight\":1,\"test_after_create\":true}" \
  | tee /tmp/model_center_connect_mock.json \
  | python3 -m json.tool
```

期望：

- `test_result.ok=true`
- `channel.health=ok`
- 返回体有 `model.provider_config.catalog_code=mock-chat`
- 返回体不包含 `api_key`、`api_key_enc`、`mock-key`

确认数据库记录：

```bash
MODEL_ID=$(python3 -c 'import json; print(json.load(open("/tmp/model_center_connect_mock.json"))["model"]["id"])')
CHANNEL_ID=$(python3 -c 'import json; print(json.load(open("/tmp/model_center_connect_mock.json"))["channel"]["id"])')

docker compose exec postgres psql -U app -d eap \
  -c "select name, provider, type, import_source, provider_config from models where id = '$MODEL_ID';"

docker compose exec postgres psql -U app -d eap \
  -c "select model_id, base_url, status, health from model_channels where id = '$CHANNEL_ID';"
```

期望：`models.import_source=catalog`，`provider_config` 里有 `catalog_code/protocol/default_base_url`；渠道 `health=ok`。

## 2. 单独重测该 channel

```bash
curl -s -X POST "http://localhost:8001/api/v1/model-center/channels/$CHANNEL_ID/test" \
  -H "Authorization: Bearer $ACCESS" \
  | tee /tmp/model_center_channel_test.json \
  | python3 -m json.tool
```

期望：`test_result.ok=true`，`channel.health=ok`。

## 3. 关键验证：错误 key 不留脏数据

用 `gpt-4o-mini` 目录项和明显错误的 key 测试。这个请求应失败，并且不创建同名 `models` 或任何关联 `model_channels`。

```bash
OPENAI_CATALOG_ID=$(curl -s http://localhost:8001/api/v1/model-center/catalog \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; print(next(x["id"] for x in json.load(sys.stdin) if x["model_code"]=="gpt-4o-mini"))')

BAD_RUNTIME="mc-bad-key-$(date +%s)"

docker compose exec postgres psql -U app -d eap \
  -c "select count(*) as models_before from models where name = '$BAD_RUNTIME';"

curl -s -o /tmp/model_center_bad_key.json -w "%{http_code}\n" \
  -X POST "http://localhost:8001/api/v1/model-center/catalog/$OPENAI_CATALOG_ID/connect" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"runtime_name\":\"$BAD_RUNTIME\",\"api_key\":\"sk-obviously-wrong\",\"weight\":1,\"test_after_create\":true}"

python3 -m json.tool /tmp/model_center_bad_key.json

docker compose exec postgres psql -U app -d eap \
  -c "select count(*) as models_after from models where name = '$BAD_RUNTIME';"

docker compose exec postgres psql -U app -d eap \
  -c "select count(*) as channels_after from model_channels c join models m on m.id = c.model_id where m.name = '$BAD_RUNTIME';"
```

期望：

- HTTP 状态是 `400`
- 响应 `detail.code=connection_test_failed`
- `models_after=0`
- `channels_after=0`

这一步证明当前实现是“先测试，失败不落库”，不会留下 `health=failed` 僵尸渠道。

## 4. runtime_name 重复校验

用第 1 步已经创建成功的 `RUNTIME_NAME` 再接一次：

```bash
curl -s -o /tmp/model_center_duplicate.json -w "%{http_code}\n" \
  -X POST "http://localhost:8001/api/v1/model-center/catalog/$MOCK_CATALOG_ID/connect" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"runtime_name\":\"$RUNTIME_NAME\",\"api_key\":\"mock-key\",\"weight\":1,\"test_after_create\":true}"

python3 -m json.tool /tmp/model_center_duplicate.json
```

期望：HTTP 状态是 `409`，响应 `detail=model_name_exists`。

## 5. 确认无密钥泄漏

```bash
grep -E 'mock-key|sk-obviously-wrong|api_key_enc' \
  /tmp/model_center_connect_mock.json \
  /tmp/model_center_channel_test.json \
  /tmp/model_center_bad_key.json \
  /tmp/model_center_duplicate.json \
  || echo "no secret fields in responses"
```

期望输出：`no secret fields in responses`。

## 6. 回归检查

老模型下拉接口仍正常：

```bash
curl -s http://localhost:8001/api/v1/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

模型纳管列表仍正常：

```bash
curl -s http://localhost:8001/api/v1/model-hub/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

MaaS 模型列表仍正常：

```bash
curl -s http://localhost:8100/v1/models | python3 -m json.tool
```

RAG 链路回归：复跑 Step 1/Step 2 已验证过的 `/kbs/{id}/retrieve`、`/agents/{id}/context`、`/chat` 三个命令即可。本步没有改 RAG 代码，重点确认服务仍能正常响应。
