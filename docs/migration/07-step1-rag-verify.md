# 07 Step 1 第一段：RAG 可见性与知识注入纯验证

本步骤只验证，不改代码。目标是确认：

1. 知识库检索接口是否真实返回片段正文。
2. 智能体绑定知识库后，上下文里是否真实注入“知识片段”。
3. SSE 对话是否返回 citation 事件。
4. 最新前端构建是否能展示命中片段正文。

如果下面全部通过，Step 1 直接结束，不需要改代码。

## 0. 强制重建并启动服务

在项目根目录执行：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend maas sandbox postgres redis minio
```

等待服务健康：

```bash
curl -s http://localhost:8001/healthz
curl -s http://localhost:8100/healthz
curl -s http://localhost:8200/healthz
curl -I http://localhost:18080
```

期望：

- backend 返回 `{"service":"backend","status":"ok","version":"0.1.0"}`
- maas 返回 `{"service":"maas","status":"ok","version":"0.1.0"}`
- sandbox 返回 `{"service":"sandbox","status":"ok","version":"0.1.0"}`
- frontend 返回 HTTP 200 或 304

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

期望：

- 能看到当前用户信息。
- `roles` 里至少有 `super_admin`，或权限里包含 `kb:create`、`agent:publish`。

## 2. 确保有一个已成功入库的知识库文档

先查看当前知识库：

```bash
curl -s http://localhost:8001/api/v1/kbs \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

如果已有知识库，取第一个：

```bash
KB_ID=$(curl -s http://localhost:8001/api/v1/kbs \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); print(rows[0]["id"] if rows else "")')

echo "KB_ID=$KB_ID"
```

如果 `KB_ID` 为空，创建一个验证知识库：

```bash
KB_ID=$(curl -s -X POST http://localhost:8001/api/v1/kbs \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Step1 RAG 验证知识库","type":"faq","description":"用于验证检索正文和智能体上下文注入","config":{"chunk_size":300,"overlap":30},"embedding_model":"mock-embedding"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "KB_ID=$KB_ID"
```

查看这个知识库已有文档：

```bash
curl -s http://localhost:8001/api/v1/kbs/$KB_ID/documents \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

判断是否已有成功入库文档：

```bash
READY_DOC_ID=$(curl -s http://localhost:8001/api/v1/kbs/$KB_ID/documents \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); ok={"done","ready","completed","success"}; print(next((x["id"] for x in rows if x.get("parse_status") in ok), ""))')

echo "READY_DOC_ID=$READY_DOC_ID"
```

期望：

- 如果 `READY_DOC_ID` 有值，说明已有可检索文档，可以进入第 3 步。
- 如果为空，必须上传一个 txt 并等待入库完成。否则检索返回空不是 bug。

### 2.1 如果没有成功入库文档，上传一个 txt

创建本地测试文档：

```bash
cat > /tmp/step1-rag-test.txt <<'EOF'
合同审批要重点检查三类事项。

第一，合同主体、签署权限、统一社会信用代码和授权文件必须一致。

第二，付款条款、验收标准、违约责任、争议解决方式需要明确，避免只写原则性描述。

第三，涉及数据、系统接口或外包服务时，需要同步检查保密条款、数据安全责任和服务等级承诺。

如果合同金额超过公司授权阈值，应进入法务、财务和业务负责人联合审批流程。
EOF
```

上传文档：

```bash
DOC_ID=$(curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_ID/documents \
  -H "Authorization: Bearer $ACCESS" \
  -F "file=@/tmp/step1-rag-test.txt;type=text/plain" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "DOC_ID=$DOC_ID"
```

轮询入库状态：

```bash
for i in $(seq 1 30); do
  STATUS=$(curl -s http://localhost:8001/api/v1/kbs/$KB_ID/documents \
    -H "Authorization: Bearer $ACCESS" \
    | python3 -c 'import sys,json,os; doc=os.environ["DOC_ID"]; rows=json.load(sys.stdin); print(next((x.get("parse_status") for x in rows if x["id"]==doc), ""))')
  echo "try=$i status=$STATUS"
  case "$STATUS" in
    done|ready|completed|success)
      break
      ;;
    failed)
      echo "文档入库失败，查看文档 meta："
      curl -s http://localhost:8001/api/v1/kbs/$KB_ID/documents \
        -H "Authorization: Bearer $ACCESS" \
        | python3 -m json.tool
      exit 1
      ;;
  esac
  sleep 2
done
```

期望：

- 最终状态为 `done`。当前代码实际使用的是 `done`，`ready/completed/success` 只是兼容以后可能的状态名。
- 如果一直是 `pending/parsing`，等待更久或查看 backend 日志。
- 如果是 `failed`，这不是检索 bug，要先解决入库失败。

再次确认可用文档：

```bash
READY_DOC_ID=$(curl -s http://localhost:8001/api/v1/kbs/$KB_ID/documents \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); ok={"done","ready","completed","success"}; print(next((x["id"] for x in rows if x.get("parse_status") in ok), ""))')

test -n "$READY_DOC_ID" && echo "ready document: $READY_DOC_ID"
```

期望：

- 输出 `ready document: <uuid>`。

## 3. curl 验证知识库命中测试返回正文

```bash
curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_ID/retrieve \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","top_k":2}' \
  | tee /tmp/step1-retrieve.json \
  | python3 -m json.tool
```

检查正文和摘要：

```bash
python3 - <<'PY'
import json
data=json.load(open("/tmp/step1-retrieve.json"))
chunks=data.get("chunks") or []
citations=data.get("citations") or []
print("chunk_count=", len(chunks))
print("citation_count=", len(citations))
print("first_content=", (chunks[0].get("content") if chunks else "")[:120])
print("first_snippet=", (citations[0].get("snippet") if citations else "")[:120])
assert chunks, "chunks is empty"
assert chunks[0].get("content"), "chunks[0].content is empty"
assert citations, "citations is empty"
assert citations[0].get("snippet"), "citations[0].snippet is empty"
PY
```

期望：

- `chunk_count` 大于 0。
- `first_content` 能看到合同审批相关正文。
- `first_snippet` 能看到摘要。
- 没有 assertion error。

如果这里失败：

- `chunks` 为空：优先检查第 2 步文档是否真的入库成功。
- `chunks[0].content` 空：这是后端 retrieve/schema 问题，第二段只修这一层。

## 4. 建一个绑定该 KB 的智能体并发布

先找一个可用 LLM 模型：

```bash
MODEL_ID=$(curl -s http://localhost:8001/api/v1/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); print(next((x["id"] for x in rows if x.get("type")=="llm"), rows[0]["id"]))')

echo "MODEL_ID=$MODEL_ID"
```

创建绑定 KB 的智能体：

```bash
AGENT_ID=$(curl -s -X POST http://localhost:8001/api/v1/agents \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"step1-rag-agent-$(date +%s)\",\"type\":\"qa\",\"model_id\":\"$MODEL_ID\",\"kb_ids\":[\"$KB_ID\"],\"tool_ids\":[],\"config\":{\"temperature\":0.2},\"persona\":\"基于企业知识库回答问题，回答需给出引用。\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

echo "AGENT_ID=$AGENT_ID"
```

发布智能体：

```bash
curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/publish \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：

- 返回智能体详情。
- `status` 为 `active`。
- `kb_ids` 中包含 `$KB_ID`。

## 5. curl 验证 agent context 里有知识片段

```bash
curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/context \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","top_k":2,"max_tokens":3500}' \
  | tee /tmp/step1-context.json \
  | python3 -m json.tool
```

检查 retrieved_chunks 和 messages：

```bash
python3 - <<'PY'
import json
data=json.load(open("/tmp/step1-context.json"))
chunks=data.get("retrieved_chunks") or []
messages=data.get("messages") or []
joined="\n".join(m.get("content","") for m in messages)
print("retrieved_chunks=", len(chunks))
print("has_knowledge_message=", "知识片段" in joined)
print("first_retrieved_content=", (chunks[0].get("content") if chunks else "")[:120])
assert chunks, "retrieved_chunks is empty"
assert "知识片段" in joined, "messages do not contain 知识片段"
PY
```

期望：

- `retrieved_chunks` 大于 0。
- `has_knowledge_message=True`。
- `first_retrieved_content` 能看到正文。

如果这里失败但第 3 步通过：

- 说明 retrieve 是好的，问题在 agent KB 绑定或 context 注入层。
- 第二段只修 `agent_service/repository/context` 中确实断掉的那处。

## 6. curl 验证 /chat SSE 返回 citation 事件

```bash
curl -N -s -X POST http://localhost:8001/api/v1/chat \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$AGENT_ID\",\"query\":\"合同审批要注意什么？\",\"top_k\":2,\"max_tool_rounds\":0}" \
  | tee /tmp/step1-chat.sse
```

检查 SSE 事件：

```bash
grep -n "event: citation" /tmp/step1-chat.sse
grep -n "event: delta" /tmp/step1-chat.sse | head
grep -n "event: done" /tmp/step1-chat.sse
```

期望：

- 至少出现一行 `event: citation`。
- 出现 `event: delta`。
- 最后出现 `event: done`。

如果没有 citation，但第 5 步 context 有 retrieved_chunks：

- 说明 SSE 输出层或 runtime 返回 citations 有问题。
- 第二段只修 chat/runtime 的 citation 返回。

## 7. 浏览器验证前端知识库页面能看到片段正文

1. 打开：

   ```text
   http://localhost:18080/kbs
   ```

2. 如果已登录，直接进入知识库页面；如果跳到登录页，使用：

   ```text
   租户：default
   用户：admin
   密码：Admin123!
   ```

3. 在浏览器里强制刷新：

   ```text
   Cmd + Shift + R
   ```

4. 在“知识库列表”里找到本次使用的知识库，点击“检索”。

5. 在“命中测试实验台”里确认右侧出现命中片段卡片。

期望：

- 页面不只显示“返回 N 条片段”。
- 能看到类似“合同审批要重点检查...”的片段正文。
- 能看到分数、来源文档或 chunk id。

如果 curl 第 3 步通过，但浏览器第 7 步看不到正文：

- 说明问题在前端展示或运行中的前端构建。
- 先确认第 0 步确实执行了 `--build frontend`，并且浏览器执行了强制刷新。
- 如果仍失败，第二段只修 `frontend/src/views/KnowledgeBaseListView.vue` 或相关类型定义，不动后端。

## 8. 判断标准

### 全部通过

Step 1 结束，不改代码，进入 Step 2：智能体绑定知识库与基础召回配置。

### 只有前端不通过

只修前端展示层或构建问题，不动后端检索、schema、context。

### retrieve 不通过

只修 `backend/app/rag/retrieve.py` 或 `backend/app/schemas/kb.py` 中确实导致正文缺失的地方。

### context 不通过

只修 `backend/app/orchestrator/context.py` 或 agent KB 绑定读取链路。

### SSE 不通过

只修 `backend/app/api/v1/chat.py` 或 `backend/app/orchestrator/runtime.py` 的 citation 返回链路。
