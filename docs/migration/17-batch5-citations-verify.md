# 17 批次5：带引用出处的知识库问答验证

本批目标：稳定返回可点击、可定位的引用出处。rerank 本批暂不实现。

## 0. 启动

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend maas postgres redis minio sandbox
```

## 1. 登录

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

## 2. 直接验证知识库检索引用字段

```bash
KB_ID=<目标知识库ID>

curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_ID/retrieve \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":3,"match_type":"keyword"}' \
  | python3 -m json.tool
```

期望：

- `citations[].doc_name` 有来源文档名
- `citations[].doc_id` 有来源文档 ID
- `citations[].chunk_id` 有切片 ID
- `citations[].seq` 有切片序号
- `citations[].content_length` 有内容长度
- `citations[].match_channels` 标明 `vector` / `keyword`
- `citations[].score/vector_score/text_score` 按命中通道返回

## 3. score_threshold 过滤验证

```bash
curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_ID/retrieve \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":3,"match_type":"vector","score_threshold":0.99}' \
  | python3 -m json.tool
```

期望：如果最高 `vector_score < 0.99`，`chunks=[]` 且 `citations=[]`，不会伪造引用。

## 4. Agent context 验证

```bash
AGENT_ID=<绑定该知识库的智能体ID>

curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/context \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"一云多芯","top_k":3,"match_type":"keyword"}' \
  | python3 -m json.tool
```

期望：

- `citations` 和 `retrieved_chunks` 一一对应
- `citations` 不重复
- system message 里的知识片段带 `[1]`、`doc`、`chunk #seq`、`chunk_id`、`score`

## 5. SSE / 前端验证

⚠️ 浏览器打开：

```text
http://localhost:18080/chat
```

选择绑定知识库的智能体并提问。

命中时：

- 右侧出现引用卡片
- 卡片标题为 `文档名 · 切片 #序号`
- 卡片展示 RRF 分、向量分、关键词分、匹配通道、chunk_id
- 点击“定位来源”后，抽屉显示文档 ID、片段 ID、切片序号和文档切片列表
- 当前引用切片高亮

未命中时：

- 右侧显示“未命中知识库或当前智能体未绑定知识库，本次回答没有使用引用出处。”
- 不生成假的引用卡片

## 6. rerank 状态

本批未实现 rerank。原因：

- 不同供应商 rerank 协议差异较大，需要新增 MaaS `/v1/rerank` 兼容层和上游适配。
- 当前批次优先保证引用链路稳定、可点击、可定位。
- 缺 rerank 时，问答仍通过 hybrid/vector/keyword 检索正常返回引用。
