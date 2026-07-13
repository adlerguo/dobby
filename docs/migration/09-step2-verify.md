# 09 Step 2 命中可解释性增强验证

本步目标：

- `match_type` 真正接通后端：`hybrid / vector / keyword`
- 命中结果返回 `seq / doc_name / content_length / match_channels`
- `score_threshold` 改为作用于 `vector_score`，不再作用于 RRF 排名分
- 前端展示向量相似度、关键词分、RRF 排名分，修正误导提示

## 1. 构建与启动

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend
```

## 2. 准备 token 和知识库

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

KB_ID=$(docker compose exec -T postgres psql -U app -d eap -tA -c \
  "select kb_id from documents where name='销售一纸禅-联通信创云.docx' order by created_at desc limit 1;")
```

## 3. hybrid 验证

```bash
curl -s -X POST "http://localhost:8001/api/v1/kbs/$KB_ID/retrieve" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":5,"match_type":"hybrid","score_threshold":0}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); c=d["chunks"][0]; print(c["score"], c["vector_score"], c["text_score"], c["match_channels"], c["seq"], c["doc_name"], c["content_length"])'
```

期望：

- `score` 约 `0.032787`
- `vector_score` 约 `0.827`
- `text_score` 约 `0.1`
- `match_channels` 包含 `vector` 和 `keyword`
- `seq` 为 `0`
- `doc_name` 为 `销售一纸禅-联通信创云.docx`

## 4. vector / keyword 模式差异

vector：

```bash
curl -s -X POST "http://localhost:8001/api/v1/kbs/$KB_ID/retrieve" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":5,"match_type":"vector","score_threshold":0}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print([(c["seq"], c["vector_score"], c["text_score"], c["match_channels"]) for c in d["chunks"]])'
```

期望：结果都有 `vector_score`，`text_score` 为 `None`，`match_channels=["vector"]`。

keyword：

```bash
curl -s -X POST "http://localhost:8001/api/v1/kbs/$KB_ID/retrieve" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":5,"match_type":"keyword","score_threshold":0.95}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print([(c["seq"], c["vector_score"], c["text_score"], c["match_channels"]) for c in d["chunks"]])'
```

期望：关键词结果不受 `score_threshold=0.95` 影响；结果无 `vector_score`，有 `text_score`，`match_channels=["keyword"]`。

## 5. score_threshold 验证

```bash
curl -s -X POST "http://localhost:8001/api/v1/kbs/$KB_ID/retrieve" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":5,"match_type":"vector","score_threshold":0.8}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print([(c["seq"], round(c["vector_score"], 3)) for c in d["chunks"]])'
```

期望：`vector_score < 0.8` 的向量结果被过滤。

## 6. 浏览器验证

1. ⚠️ 打开 `http://localhost:18080/kbs` 并强制刷新。
2. ⚠️ 对包含 `销售一纸禅-联通信创云.docx` 的知识库检索 `一云多芯`。
3. 期望命中卡片显示：
   - 文档名 · 切片 #0
   - 向量相似度
   - 关键词分
   - RRF 排名分
   - 向量/关键词通道标签
   - 内容长度
4. ⚠️ 切换检索模式：
   - `向量`：只显示向量通道，关键词分显示“未命中该通道”
   - `关键词`：只显示关键词通道，向量相似度显示“未命中该通道”
   - `混合`：可能同时显示两个通道
5. ⚠️ 调整 Score Threshold。
   - 说明文案应为“向量相似度阈值（仅过滤向量通道）”
   - 不再出现基于 RRF 分数的误导性低分警告

## 7. 主链路回归

Agent 上下文：

```bash
AGENT_ID=$(docker compose exec -T postgres psql -U app -d eap -tA -c \
  "select id from agents where status='active' order by created_at desc limit 1;")

curl -s -X POST "http://localhost:8001/api/v1/agents/$AGENT_ID/context" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯是什么？","top_k":2,"match_type":"hybrid","score_threshold":0}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d["retrieved_chunks"]), d["truncation"]["rag"])'
```

期望：有 retrieved chunks，`truncation.rag.match_type` 为 `hybrid`。

Public API：

如果已有发布应用和明文 key，可继续用原 Step 4 的 public chat 验证。否则本步只要求确认内部 `/chat` 或 `/agents/{id}/context` 未受影响。
