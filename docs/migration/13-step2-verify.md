# Step 2 验证：模型中心目录接口与前端模型广场

本步只新增 `model_catalog` 只读查询接口，并在现有“模型纳管/模型中心”页面展示目录卡片。不创建模型、不创建渠道、不接触 API Key。

## 0. 前置启动

改了 backend 和 frontend，必须重新构建镜像：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend postgres redis minio maas sandbox
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

## 1. 目录列表返回 7 条并带 availability

```bash
curl -s http://localhost:8001/api/v1/model-center/catalog \
  -H "Authorization: Bearer $ACCESS" \
  | tee /tmp/model_catalog.json \
  | python3 -m json.tool

python3 - <<'PY'
import json
items = json.load(open('/tmp/model_catalog.json'))
print('count=', len(items))
print([(x['model_code'], x['recommended_parameters'].get('availability')) for x in items])
assert len(items) == 7
assert all('availability' in x['recommended_parameters'] for x in items)
PY
```

期望：`count= 7`，其中 `mock-chat/mock-embedding` 是 `verified_local`，商业模型是 `needs_real_key`。

## 2. 按类型过滤

```bash
curl -s "http://localhost:8001/api/v1/model-center/catalog?model_type=llm" \
  -H "Authorization: Bearer $ACCESS" \
  | tee /tmp/model_catalog_llm.json \
  | python3 -m json.tool

python3 - <<'PY'
import json
items = json.load(open('/tmp/model_catalog_llm.json'))
print('count=', len(items))
print(sorted(set(x['model_type'] for x in items)))
assert items
assert all(x['model_type'] == 'llm' for x in items)
PY
```

期望：只返回 `model_type=llm` 的目录项。

## 3. 目录详情

```bash
CATALOG_ID=$(python3 - <<'PY'
import json
items = json.load(open('/tmp/model_catalog.json'))
print(items[0]['id'])
PY
)

curl -s "http://localhost:8001/api/v1/model-center/catalog/$CATALOG_ID" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：返回单条目录详情，包含 `provider/model_code/display_name/model_type/default_base_url/protocol/recommended_parameters` 等公共字段，不包含任何 `api_key/key_hash/tenant_id`。

## 4. ⚠️ 浏览器手动验证模型广场

1. 打开 `http://localhost:18080/model-hub`，必要时按 `Cmd+Shift+R` 强制刷新。
2. 页面内应看到“模型广场”卡片区。
3. `mock-chat`、`mock-embedding` 卡片标注为“可直接体验”。
4. `deepseek-chat`、`deepseek-reasoner`、`gpt-4o-mini`、`text-embedding-3-small`、`qwen-plus` 标注为“需自备 API Key”。
5. “接入使用”按钮点击后只提示“下一步实现”，不会创建模型或渠道。

## 5. 回归：现有模型纳管功能

用接口快速回归创建、启停、查看渠道：

```bash
TEST_MODEL="step2-regression-$(date +%s)"

MODEL_ID=$(curl -s -X POST http://localhost:8001/api/v1/model-hub/models \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"$TEST_MODEL\",\"provider\":\"mock\",\"type\":\"llm\",\"display_name\":\"Step2回归模型\",\"default_channel\":{\"base_url\":\"mock://local\",\"api_key\":\"test-key\",\"weight\":1,\"status\":\"active\"}}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

curl -s -X POST "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID/status" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"is_active":false}' \
  | python3 -m json.tool

curl -s "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID/channels" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：

- 创建成功并返回 `MODEL_ID`。
- 停用接口返回 `is_active=false`。
- 渠道列表能看到 `base_url=mock://local`，不返回密钥明文或 `api_key_enc`。

前端也可以手动验证：在同一页面下方“已接入模型”区域，新建模型、启停模型、打开渠道抽屉仍正常。
