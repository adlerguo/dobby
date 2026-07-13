# 知识库命中率问题诊断

日期：2026-07-13

范围：只诊断，不改代码。诊断对象为真实入库文档 `销售一纸禅-联通信创云.docx`。

## 1. 切分实况

### 1.1 目标文档与知识库

SQL：

```sql
select d.id, d.kb_id, d.name, d.mime, d.parse_status, d.created_at,
       kb.name as kb_name, kb.embedding_model, kb.config
from documents d
join knowledge_bases kb on kb.id = d.kb_id
where d.name ilike '%联通信创云%' or d.name ilike '%一纸禅%'
order by d.created_at desc
limit 10;
```

结果：

| id | kb_id | name | mime | parse_status | created_at | kb_name | embedding_model | config |
|---|---|---|---|---|---|---|---|---|
| `0181d6d4-fc0f-4835-8c9e-6362f79d0219` | `6b65266e-57fa-4aa5-87e5-7d2fdbe248c9` | 销售一纸禅-联通信创云.docx | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `done` | `2026-07-13 04:57:07.034181+00` | Vue 测试知识库0713-1 | `mock-embedding` | `{}` |

结论：该知识库没有自定义切分配置，实际使用默认 `chunk_size=800`、`overlap=80`。

证据：`backend/app/rag/ingest.py` 读取 `(kb.config or {}).get("chunk_size", 800)` 和 `(kb.config or {}).get("overlap", 80)`。

### 1.2 切片数量与长度分布

SQL：

```sql
with target as (
  select id from documents
  where name = '销售一纸禅-联通信创云.docx'
  order by created_at desc
  limit 1
)
select count(*) as chunk_count,
       min(length(content)) as min_chars,
       max(length(content)) as max_chars,
       round(avg(length(content))::numeric, 2) as avg_chars,
       min(tokens) as min_tokens,
       max(tokens) as max_tokens,
       round(avg(tokens)::numeric, 2) as avg_tokens
from chunks
where doc_id = (select id from target);
```

结果：

| chunk_count | min_chars | max_chars | avg_chars | min_tokens | max_tokens | avg_tokens |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 715 | 779 | 739.33 | 16 | 17 | 16.33 |

SQL：

```sql
with target as (
  select id from documents
  where name = '销售一纸禅-联通信创云.docx'
  order by created_at desc
  limit 1
)
select seq,
       length(content) as chars,
       tokens,
       left(regexp_replace(content, E'[\\n\\r\\t]+', ' ', 'g'), 100) as preview
from chunks
where doc_id = (select id from target)
order by seq
limit 3;
```

结果：

| seq | chars | tokens | preview |
|---:|---:|---:|---|
| 0 | 779 | 16 | 销售一纸禅-联通信创云 产品定位 联通信创云是面向党政、央国企、泛政务等客户的安全可靠云平台和迁移服务方案，基于联通云7信创云平台，提供一云多芯、虚拟化+云原生双引擎、信创数据库/中间件云化封装、统一 |
| 1 | 724 | 17 | 迁移服务：按业务调研、迁移准备、改造验证、业务切换、试运行上线五阶段推进，支持迁移亲和度评价、适配迁移、重构迁移、自然淘汰策略。 统一运营：支持多云商纳管、统一门户、资源开通、监控告警、日志管理、工单 |
| 2 | 715 | 16 | 实践成熟：中国联通服务21部委、25省级政务云、140+地市政务云；联通信创政务云已建设3500+信创服务器、提供420000+核vCPU、部署3800+业务系统。 生态完备：已与主流信创CPU、操作 |

完整长度序列：

| seq | chars |
|---:|---:|
| 0 | 779 |
| 1 | 724 |
| 2 | 715 |

### 1.3 解析与切分代码

证据：

- `backend/app/rag/parsers.py`
  - `parse_docx()` 使用 `python-docx` 读取非空段落：`paragraph.text.strip()`。
  - 返回值是 `"\n\n".join(paragraphs)`，即“按段落保留空行分隔的整篇字符串”。
- `backend/app/rag/chunking.py`
  - `chunk_text()` 先按 `"\n\n"` 拆成段落。
  - 单段超过 `chunk_size` 时由 `split_long_paragraph()` 按长度窗口切分。
  - 多段组合时，只要组合后长度 `<= chunk_size`，就继续合并进当前 chunk。
  - chunk 元信息为 `{"chunk_method": "paragraph_window"}`。
- `backend/app/rag/ingest.py`
  - 默认 `chunk_size=800`、`overlap=80`。
  - 每个 chunk 入库时保存 `seq/content/tokens/meta/embedding`。

### 1.4 切分结论

切分没有完全失效：该 docx 被切成 3 片，不是整篇 1 片。

但切片偏大：每片约 715-779 个中文字符。源文档本身是“一纸禅”短文，内容密度高，所以第一片覆盖“产品定位、目标客户、产品背景、产品功能”等多个小节，肉眼看起来像“整篇文档进了一个片段”。

根因在切分层的默认策略，不是 docx 解析层：

- 解析层已经保留段落分隔。
- 切分层会把多个短段落合并到接近 `chunk_size=800` 才落片。
- 当前 `tokens=len(chunk.content.split())` 对中文文本不准确，空格少导致 tokens 只有 16-17，不能反映真实中文长度。

优先修复方向：提供可配置更小 `chunk_size`，或按标题/段落数量做更细粒度切分，并提供重切/重建索引能力。

## 2. 打分逻辑

### 2.1 当前检索代码

证据文件：`backend/app/rag/retrieve.py`

当前 `retrieve_chunks()` 实际流程：

1. 根据知识库 `embedding_model` 调 MaaS `/v1/embeddings` 得到查询向量。
2. `vector_search()` 用 `Chunk.embedding.cosine_distance()` 做向量召回，返回 `vector_score = 1 - cosine_distance`。
3. `text_search()` 用 PostgreSQL `to_tsvector('simple', chunks.content) @@ plainto_tsquery('simple', :query)` 做全文召回，返回 `text_score = ts_rank_cd(...)`。
4. `merge_candidates()` 合并两路候选。
5. 最终 `score` 不是向量相似度，而是 `hybrid_score()` 的 RRF 排名分：

```python
score = 0.0
if candidate.vector_rank is not None:
    score += 1 / (60 + candidate.vector_rank)
if candidate.text_rank is not None:
    score += 1 / (60 + candidate.text_rank)
return round(score, 6)
```

### 2.2 “vector/keyword/hybrid 模式”现状

当前后端没有真正暴露 `vector/keyword/hybrid` 三种检索模式。

证据：

- `backend/app/schemas/kb.py` 的 `RetrieveIn` 只有 `query` 和 `top_k`。
- `backend/app/api/v1/kbs.py` 调 `retrieve_chunks(..., query=payload.query, top_k=payload.top_k)`，没有传 `match_type`。
- `frontend/src/views/KnowledgeBaseListView.vue` 有 `retrieveMode` 控件，但请求体只发送 `{ query, top_k }`。

结论：前端选择“向量/关键词/混合”目前只是 UI 状态，未影响后端检索。后端实际总是混合召回。

### 2.3 真实查询“一云多芯”的返回

调用：

```bash
curl -s -X POST "http://localhost:8001/api/v1/kbs/6b65266e-57fa-4aa5-87e5-7d2fdbe248c9/retrieve" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":5}'
```

关键结果：

| rank | chunk_id | score | vector_score | text_score | 说明 |
|---:|---|---:|---:|---:|---|
| 1 | `7148e43b-a1f3-4363-b974-5a66cd5dcfbf` | 0.032787 | 0.8270882701635439 | 0.10000000149011612 | 同时命中向量与全文 |
| 2 | `2b5ed9dc-d744-4273-b5a9-0a2db5fd8888` | 0.016129 | 0.8176483229663917 | null | 仅向量候选 |
| 3 | `bb9d9abb-f6a4-4ac9-944d-d4b7f1c63167` | 0.015873 | 0.713438633172089 | null | 仅向量候选 |

结论：用户看到的 `0.033` 是 RRF 混合排名分，不是“向量相似度很低”。真正的 `vector_score` 是 0.827。

### 2.4 mock embedding 语义问题

知识库配置：

| kb_id | name | embedding_model | config |
|---|---|---|---|
| `6b65266e-57fa-4aa5-87e5-7d2fdbe248c9` | Vue 测试知识库0713-1 | `mock-embedding` | `{}` |

证据文件：

- `backend/app/rag/embeddings.py` 调 MaaS `/v1/embeddings`。
- `maas/app/api/openai.py` 中 mock 渠道调用 `mock_embedding_response()`。
- `maas/app/services.py` 的 `mock_embedding_response()`：

```python
digest = hashlib.sha256(text.encode("utf-8")).digest()
seed = [byte / 255 for byte in digest]
embedding = (seed * ((1536 // len(seed)) + 1))[:1536]
```

结论：`mock-embedding` 是 SHA256 哈希向量重复填充到 1536 维，不具备语义相似能力。它只能验证链路，不适合评估命中率。

### 2.5 向量维度

SQL：

```sql
\d chunks
```

关键结果：

```text
embedding | vector(1536)
Indexes:
  ix_chunks_embedding hnsw (embedding vector_cosine_ops)
```

证据文件：`backend/app/models/entities.py` 中 `Chunk.embedding = mapped_column(Vector(1536))`。

结论：第一批真实 embedding 应优先选 1536 维模型，例如 `text-embedding-3-small`。如果接入通义等非 1536 维模型，需要迁移向量列或设计多维度索引方案。

## 3. 命中结果可解释性现状

### 3.1 后端返回字段

证据文件：`backend/app/schemas/kb.py`

`RetrievedChunkOut` 当前返回：

- `id`
- `doc_id`
- `content`
- `score`
- `vector_score`
- `text_score`
- `meta`

`CitationOut` 当前返回：

- `chunk_id`
- `doc_id`
- `doc_name`
- `score`
- `snippet`

### 3.2 后端有但前端没充分展示的信息

前端文件：`frontend/src/views/KnowledgeBaseListView.vue`

当前命中测试结果展示：

- 片段标题：通过 citation 展示 `doc_name`
- 标签：展示 `score`
- 标签：展示前端本地 `retrieveMode`
- 内容：展示 `chunk.content`
- ID：展示 `chunk_id`

前端未展示或展示不足：

- `vector_score`
- `text_score`
- chunk `seq` 序号：数据库有 `chunks.seq`，但后端 schema 未返回
- chunk 字符长度：前端可由 `content.length` 计算，但当前未展示
- 匹配来源：目前只能通过 `vector_score/text_score` 是否为空推断，前端未展示
- 文档解析/切片详情：当前只显示文档列表，没有切片列表

### 3.3 后端也缺的可解释性字段

数据库有但接口未返回：

- `chunks.seq`
- `length(content)`
- `tokens`
- `created_at`

当前 `chunks.meta` 只有 `{"chunk_method": "paragraph_window"}`，没有原始段落编号、页码、标题路径等信息。

## 4. 诊断结论与修复优先级

### 结论排序

1. **mock embedding 无语义能力，是命中率判断失真的最大因素。**
   - 当前知识库使用 `mock-embedding`。
   - mock 向量来自文本 SHA256，不表达语义。
   - 预期提升：换真实 embedding 后，相似召回质量会发生实质提升，尤其是同义表达、长问题、非精确关键词场景。

2. **用户看到的 0.033 是 RRF 排名分，不是向量相似度。**
   - 第一条实际 `vector_score=0.827`，`text_score=0.1`。
   - 当前 UI 把 `score` 当作唯一分数展示，容易误判“向量分低”。
   - 预期提升：展示 `vector_score/text_score/score` 三个指标后，问题定位会清楚很多。

3. **切分没有失效，但默认切片偏大。**
   - 真实数据为 3 片，平均 739 字符。
   - 对“一纸禅”这类短文，800 字符窗口会把多个小节合并到同一片。
   - 预期提升：改为更小 chunk size 或标题感知切分后，引用片段更短、更聚焦；对关键词定位和回答可读性有提升。

4. **前端检索模式控件未接后端。**
   - 现在选择“向量/关键词/混合”不会改变接口行为。
   - 预期提升：接入 `match_type` 后，可以分别诊断向量召回和关键词召回。

5. **缺切片可视化，导致定位成本高。**
   - 当前只能靠 SQL 看切片。
   - 预期提升：前端能直接看每个文档切成什么样，录制演示和后续调参会更顺畅。

## 5. 分步施工计划

### Step 1：切片可视化

目标：前端文档面板增加“查看切片”，让用户能看到文档被切成了什么样。

建议实现：

- 后端新增只读接口：`GET /api/v1/documents/{document_id}/chunks`
- 返回字段：
  - `id`
  - `seq`
  - `content`
  - `content_length`
  - `tokens`
  - `meta`
  - `has_embedding`
  - `created_at`
- 前端文档管理抽屉：
  - 文档列表增加“查看切片”
  - 切片列表展示：序号、长度、向量状态、内容全文

改动文件：

- `backend/app/api/v1/kbs.py`
- `backend/app/schemas/kb.py`
- `backend/app/repositories/kb_repository.py` 或直接查询 `Chunk`
- `frontend/src/api/types.ts`
- `frontend/src/views/KnowledgeBaseListView.vue`

验证：

- 上传 `销售一纸禅-联通信创云.docx`
- 前端打开切片面板，能看到 3 片，长度约 779/724/715。

### Step 2：命中可解释性增强

目标：命中片段标注 chunk 序号、所属文档、vector/keyword 双通道分数。

建议实现：

- 后端 `RetrievedChunkOut` 补充：
  - `seq`
  - `doc_name`
  - `content_length`
  - `match_channels`，例如 `["vector", "keyword"]`
- 前端命中卡片展示：
  - 文档名 + chunk 序号
  - `score`
  - `vector_score`
  - `text_score`
  - 内容长度

同时修正“检索模式”：

- `RetrieveIn` 增加 `match_type: hybrid|vector|keyword`
- `retrieve_chunks()` 根据 `match_type` 控制召回路径。

验证：

- 查询“一云多芯”
- 第一条应显示 `vector_score=0.827...`、`text_score=0.1...`，匹配来源为 `vector + keyword`。

### Step 3：真实 embedding 接入与重建索引

目标：用真实 embedding 替换 `mock-embedding`，让命中率评估有意义。

关键约束：

- 当前 `chunks.embedding` 是 `vector(1536)`。
- 首选 `text-embedding-3-small`，维度匹配 1536。
- 如果选通义 embedding，需先确认维度；非 1536 维不能直接写入当前列。

建议实现：

- 模型中心接入真实 embedding 模型。
- 知识库创建/编辑时可选择 embedding model。
- 提供“重建索引”按钮：
  - 重新解析现有文档或复用原文对象存储。
  - 删除旧 chunks。
  - 用当前知识库 embedding model 重新生成向量。

不建议只让用户“重传文档”：演示可以临时用，但产品上不可接受。

验证：

- 同一文档分别用 mock 与真实 embedding 建索引。
- 对“一云多芯”“支持哪些 CPU 路线”“信创云适合哪些客户”等问题对比召回质量。

### Step 4：切分修复与重切能力

触发条件：Step 1 可视化后确认切片粒度不符合产品预期。

建议实现：

- 知识库配置增加：
  - `chunk_size`
  - `overlap`
  - `split_by_heading`
  - `max_paragraphs_per_chunk`
- docx 解析增强：
  - 可识别标题样式或短行标题。
  - chunk meta 写入标题路径。
- 提供“重切并重建索引”：
  - 改配置后可对单文档或整个知识库重建。

验证：

- 将 chunk_size 调为 300-500。
- 重建后该 docx 应从 3 片变为更多、更聚焦的小片。
- 命中“一云多芯”时引用应集中在产品定位/产品功能相关片段。

## 6. 建议执行顺序

建议先做：

1. Step 1 切片可视化
2. Step 2 命中可解释性增强
3. Step 3 真实 embedding 接入 + 重建索引
4. Step 4 切分修复

原因：先把“看得见”补齐，再调整检索和向量模型。否则每次优化都只能靠 SQL 和猜测验证，录制演示和产品调参都会很难。
