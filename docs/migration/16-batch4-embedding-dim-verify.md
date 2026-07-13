# 16 批次4：知识库 embedding 维度可配置验证

本批目标：解除知识库向量维度 `1536` 硬编码，支持按知识库固定维度路由到对应 chunk 表。

## 0. 启动和迁移

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

docker compose up -d --build backend maas frontend postgres redis minio sandbox
docker compose exec backend alembic upgrade head
```

期望：

- 迁移日志出现 `202607130001`。
- `knowledge_bases` 有 `embedding_dim`。
- `chunks_1024`、`chunks_3072` 建成。
- 旧 `chunks` 表仍存在，作为 1536 维存储。
- pgvector HNSW 索引上限为 2000 维，因此 `chunks_3072` 暂不建 HNSW 向量索引，3072 维先走精确向量排序；1024 和 1536 维有 HNSW。
- 重要限制：3072 维适合小型知识库。大库建议选择 1024/1536 维 embedding，或通过 provider 的 `dimensions` 参数把 `text-embedding-3-large` 降到 2000 维以内后再规划索引方案。否则数据量变大后，3072 维检索会因为精确扫描明显变慢。
- 重要限制：知识库一旦上传过文档，embedding 模型和 `embedding_dim` 会被锁定。禁止直接切换到其他维度模型，避免旧 chunks 留在原维度表里，造成“文档还在但检索不到”的孤立数据。需要换模型时，请新建知识库并重新上传文档。

```bash
docker compose exec postgres psql -U app -d eap -c '\d knowledge_bases'
docker compose exec postgres psql -U app -d eap -c '\d chunks'
docker compose exec postgres psql -U app -d eap -c '\d chunks_1024'
docker compose exec postgres psql -U app -d eap -c '\d chunks_3072'
```

## 1. 登录

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

## 2. 验证 MaaS embedding probe 返回实际维度

已接入 embedding 渠道后，点击模型中心“重新测试”，或用接口：

```bash
CHANNEL_ID=<embedding_channel_id>

curl -s -X POST http://localhost:8001/api/v1/model-center/channels/$CHANNEL_ID/test \
  -H "Authorization: Bearer $ACCESS"
```

期望：

- `test_result.ok=true`
- `test_result.embedding_dim` 返回真实维度，例如 `1024`、`1536` 或 `3072`

如果供应商返回维度与目录预置 `dimensions` 不一致，期望返回：

```json
{"code":"connection_test_failed","summary":"dimension_mismatch"}
```

## 3. 1024 维 BGE-large-zh 建库验证

前提：模型中心已接入一个 1024 维 embedding 模型，例如 BGE-large-zh，runtime name 示例为 `bge-large-zh-1024`。

```bash
KB_1024=$(curl -s -X POST http://localhost:8001/api/v1/kbs \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"BGE 1024维测试库","type":"material","embedding_model":"bge-large-zh-1024"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

curl -s http://localhost:8001/api/v1/kbs/$KB_1024 \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：`embedding_dim=1024`。

上传文档：

```bash
printf '国产化云平台支持鲲鹏、飞腾、海光、龙芯等 CPU 路线。' > /tmp/kb-1024.txt

curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_1024/documents \
  -H "Authorization: Bearer $ACCESS" \
  -F "file=@/tmp/kb-1024.txt;type=text/plain"
```

等待文档 `parse_status=done` 后检查分表：

```bash
docker compose exec postgres psql -U app -d eap \
  -c "select count(*) from chunks_1024 where kb_id='$KB_1024';"
```

检索：

```bash
curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_1024/retrieve \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"支持哪些国产CPU路线","top_k":3,"match_type":"hybrid"}' \
  | python3 -m json.tool
```

期望：返回命中片段。

## 4. 1536 维 text-embedding-3-small 建库验证

前提：模型中心已接入 1536 维 embedding 模型，runtime name 示例为 `text-embedding-3-small`。

```bash
KB_1536=$(curl -s -X POST http://localhost:8001/api/v1/kbs \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"OpenAI 1536维测试库","type":"material","embedding_model":"text-embedding-3-small"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

curl -s http://localhost:8001/api/v1/kbs/$KB_1536 \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：`embedding_dim=1536`。

上传并检索：

```bash
printf '合同审批需要关注主体资质、付款条件、违约责任和授权边界。' > /tmp/kb-1536.txt

curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_1536/documents \
  -H "Authorization: Bearer $ACCESS" \
  -F "file=@/tmp/kb-1536.txt;type=text/plain"

docker compose exec postgres psql -U app -d eap \
  -c "select count(*) from chunks where kb_id='$KB_1536';"

curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_1536/retrieve \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批关注什么","top_k":3,"match_type":"hybrid"}' \
  | python3 -m json.tool
```

期望：1536 维库写入旧 `chunks` 表，检索正常。

## 5. 3072 维 text-embedding-3-large 验证

前提：模型中心接入 `text-embedding-3-large`，目录或渠道默认参数不要设置 `dimensions:1536`，让它返回 3072 维，或显式设为 3072。

注意：3072 维当前不建 HNSW 索引，适合小库验证和低频检索。客户生产大库不要默认选择 3072 维，除非接受精确扫描成本，或后续升级 halfvec/HNSW、降维到 2000 以内、分片索引等方案。

创建库后期望：

- `embedding_dim=3072`
- 上传文档后切片进入 `chunks_3072`
- 检索只查 `chunks_3072`

## 6. 并存互不干扰

```bash
docker compose exec postgres psql -U app -d eap \
  -c "select embedding_dim, count(*) from knowledge_bases group by embedding_dim order by embedding_dim;"

docker compose exec postgres psql -U app -d eap \
  -c "select '1024' as dim, count(*) from chunks_1024 union all select '1536', count(*) from chunks union all select '3072', count(*) from chunks_3072;"
```

期望：

- 1024 / 1536 / 3072 的库可以同时存在。
- 各自文档进入各自维度表。
- 对任一知识库检索不会跨维度表。

## 7. 老 1536 数据回归

选择已有老知识库：

```bash
curl -s http://localhost:8001/api/v1/kbs \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：老库返回 `embedding_dim=1536`。

对老库执行原有命中测试：

```bash
OLD_KB_ID=<old_1536_kb_id>

curl -s -X POST http://localhost:8001/api/v1/kbs/$OLD_KB_ID/retrieve \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":3,"match_type":"hybrid"}' \
  | python3 -m json.tool
```

期望：仍可从旧 `chunks` 表检索到原有内容。

## 8. 前端验证

⚠️ 浏览器打开：

```text
http://localhost:18080/kbs
```

检查：

1. 知识库列表出现“维度”列。
2. 创建知识库时选择不同 embedding 模型，保存后维度显示正确。
3. 上传文档、查看切片、命中测试仍正常。
4. 设置页提示改为“支持 1024 / 1536 / 3072 维”，不再误导为只能 1536 维。

## 9. 已有文档后禁止切换 embedding 模型

选择一个已有文档的知识库，尝试修改 `embedding_model`：

```bash
KB_WITH_DOCS=<has_documents_kb_id>

curl -i -X PATCH http://localhost:8001/api/v1/kbs/$KB_WITH_DOCS \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"embedding_model":"bge-large-zh-1024"}'
```

期望：

- HTTP 409
- `detail=kb_embedding_model_locked_has_documents`
- 原知识库的 `embedding_model` 和 `embedding_dim` 不变
- 前端显示“该知识库已有文档，embedding 模型和维度已锁定”

空知识库仍允许切换 embedding 模型，切换时会重新 probe 并写入新的 `embedding_dim`。
