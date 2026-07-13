# 10 Step 3 真实 embedding 接入与重建索引验证

本步目标：

- 知识库可切换 `embedding_model`
- 可触发知识库级重建索引
- 重建索引使用当前知识库 `embedding_model` 重新解析、切分、向量化并替换 chunks
- `chunks.embedding` 是 `vector(1536)`，embedding 维度不等于 1536 时文档标记 `failed`，错误记录为 `dimension_mismatch`

## 1. 构建与启动

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend
```

## 2. 本地 mock 回归验证

登录：

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

KB_ID=$(docker compose exec -T postgres psql -U app -d eap -tA -c \
  "select kb_id from documents where name='销售一纸禅-联通信创云.docx' order by created_at desc limit 1;")
```

触发重建：

```bash
curl -s -X POST "http://localhost:8001/api/v1/kbs/$KB_ID/reindex" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{}' \
  | python3 -m json.tool
```

期望：

```json
{
  "kb_id": "...",
  "document_count": 1,
  "status": "queued"
}
```

等待并检查文档状态：

```bash
sleep 3
docker compose exec -T postgres psql -U app -d eap -P pager=off -c \
  "select name, parse_status, meta->'ingest_task' as ingest_task from documents where kb_id='$KB_ID' order by created_at desc;"
```

期望：目标文档回到 `done`，`ingest_task.status=done`。

检查切片仍正常：

```bash
docker compose exec -T postgres psql -U app -d eap -P pager=off -c \
  "select seq, length(content) as chars, embedding is not null as has_embedding from chunks where kb_id='$KB_ID' order by seq;"
```

## 3. 浏览器验证

1. ⚠️ 打开 `http://localhost:18080/kbs` 并强制刷新。
2. ⚠️ 在知识库列表看到 `Embedding` 列。
3. ⚠️ 点击目标知识库“设置”。
   - 期望：可选择 embedding 模型。
   - 期望：有 1536 维兼容性提示。
4. ⚠️ 更换 embedding 模型时应弹出确认提示：已有向量需重建索引。
5. ⚠️ 点击“重建”。
   - 期望：确认弹窗说明会重新解析并重新生成向量。
   - 期望：文档状态可见地进入 `解析中` 或很快回到 `完成`。
6. ⚠️ 文档完成后，命中测试仍正常。

## 4. 真实 embedding 接入路径

⚠️ 使用真实 key 验证：

1. 打开模型中心。
2. 找到 `text-embedding-3-small` 或 `通义 text-embedding-v4` 目录项。
   - `通义 text-embedding-v4` 的类型必须显示为 `Embedding`。
   - 接入弹窗会明确提示“正在接入 Embedding 类型模型”。
3. 点击“接入使用”，填写真实 API Key。
4. 连接测试通过后，模型会出现在已接入模型里。
5. 回到知识库实验台。
6. 点击目标知识库“设置”，把 `embedding_model` 改为新接入的 embedding runtime name。
7. 点击“重建”并等待文档完成。

### 通义 text-embedding-v4 说明

已新增目录项：

- `provider=qwen`
- `model_code=text-embedding-v4`
- `display_name=通义 text-embedding-v4`
- `model_type=embedding`
- `default_base_url=https://dashscope.aliyuncs.com/compatible-mode`
- `recommended_parameters={"dimensions":1536,"availability":"needs_real_key"}`

MaaS 会把模型目录的 `recommended_parameters` 中除 `availability` 外的参数写入 `models.provider_config.request_defaults`，调用上游 OpenAI 兼容 Embedding 接口时自动合并进请求体。因此通义 `text-embedding-v4` 会自动携带 `dimensions=1536`，适配当前 `chunks.embedding vector(1536)`。

阿里云官方文档确认 `text-embedding-v4` 支持 `2048、1536、1024（默认）、768、512、256、128、64` 等维度；OpenAI 兼容接口文档也说明该模型兼容 OpenAI Embedding 接口。

## 4.1 错误接入的修正路径

如果从 `通义千问 Plus` 这类 LLM 目录项接入，并把 runtime name 填成 `text-embedding-v4`：

- 后端会按目录项创建 `type=llm` 的模型，这是符合当前设计的。
- 知识库设置页只筛选 `type=embedding`，因此不会看到这条错误模型。

修正方式：

1. 推荐：停用错误模型，重新从 `通义 text-embedding-v4` 目录项接入。
2. 后端纠错能力：`PATCH /api/v1/model-hub/models/{model_id}` 已支持修改 `type` 字段。需要管理员明确确认后可用 API 修正：

```bash
curl -s -X PATCH "http://localhost:8001/api/v1/model-hub/models/$MODEL_ID" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"type":"embedding"}'
```

前端本批次不开放模型类型编辑，避免误把真实 LLM 改成 Embedding。

## 5. 重建前后对比测试

建议记录三组问题的 `vector_score`。

### A. 原文含关键词

问题：

```text
一云多芯
```

预期：真实 embedding 与 mock 都可能命中，但真实 embedding 的结果更有语义稳定性。

### B. 语义问题

问题：

```text
支持哪些国产CPU路线
```

原文表述：

```text
支持鲲鹏、飞腾、海光、龙芯、申威等多CPU路线
```

预期：mock embedding 容易不稳定；真实 embedding 应更容易命中切片 #0 或相关片段，并给出更合理的 `vector_score`。

### C. 无关问题

问题：

```text
红烧肉怎么做
```

预期：真实 embedding 下 `vector_score` 应明显低于相关问题，体现区分度。

curl 示例：

```bash
curl -s -X POST "http://localhost:8001/api/v1/kbs/$KB_ID/retrieve" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"支持哪些国产CPU路线","top_k":3,"match_type":"vector","score_threshold":0}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print([(c["seq"], c["vector_score"], c["doc_name"]) for c in d["chunks"]])'
```

## 6. 维度护栏

代码护栏位置：

- `backend/app/rag/ingest.py`
- 逻辑：`if any(len(embedding) != 1536 for embedding in embeddings): raise ValueError("dimension_mismatch")`
- `maas/app/services.py`
- 逻辑：连接测试 / 重测 embedding 渠道时会检查上游返回的第一条 embedding 是否为 1536 维，非 1536 返回 `dimension_mismatch`

验证方式：

- 接入或模拟一个非 1536 维 embedding 模型后触发重建。
- 期望：文档 `parse_status=failed`，`documents.meta.ingest_task.error=dimension_mismatch`。

如果当前没有可用的非 1536 维模型，本项以代码路径确认即可；不要为了验证维度错误修改生产模型配置。

## 7. 原文来源与降级方案

正常路径：

- 上传文档时原文保存在 MinIO，`documents.source_uri` 指向 `s3://...`
- 重建索引优先从 MinIO 下载原文后重新解析

降级路径：

- 对于缺少原文的历史/seed 文档，强制重建会按现有 chunks 的 `seq` 顺序拼回文本，再重新切分和向量化
- 如果原文和旧 chunks 都不可用，文档会标记 `failed`，错误为 `source_document_unavailable`

## 8. 回归

- ⚠️ mock-embedding 知识库检索仍正常。
- ⚠️ Agent 对话带引用正常。
- ⚠️ Public API 调用正常。

## 9. 命中上下文与低分提示收尾验证

1. ⚠️ 在知识库命中测试中点击某条命中卡片的“查看上下文”。
   - 期望：弹窗展示当前切片及其前后相邻切片。
   - 期望：当前命中切片带“当前命中”标签和高亮背景。
   - 期望：若当前片是首片，只展示当前片和后一片；若是末片，只展示前一片和当前片。
2. ⚠️ 查询明显无关问题，例如：

```text
红烧肉怎么做
```

期望：如果最高 `vector_score < 0.5`，警告文案为：

```text
未检索到高相关内容（最高向量相似度低于 0.5），可能知识库中没有该问题相关的资料，或可尝试调整问题表述。
```

3. ⚠️ 回归：命中卡片三分数展示仍正常：
   - 向量相似度
   - 关键词分
   - RRF 排名分
