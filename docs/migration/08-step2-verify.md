# 08 Step 2：智能体绑定知识库与基础召回参数验证

本步骤验证用户能在前端创建/编辑智能体时选择知识库，并把基础 RAG 参数写入 `agent.config.rag`。

## 本步参数生效范围

- `top_k`：已生效。优先级是：请求体显式传 `top_k` -> `agent.config.rag.top_k` -> 系统默认 4。
- `score_threshold`：已生效。优先级是：请求体显式传 `score_threshold` -> `agent.config.rag.score_threshold` -> 系统默认 0。后端会在多知识库召回合并排序后过滤低于阈值的片段。
- `match_type`：本步先保存为产品契约占位。当前 `retrieve_chunks` 仍只有 hybrid 召回实现，`vector/keyword` 不改变实际检索模式，后续检索模块升级时再接入。

## 0. 重建并启动

前端 dist 已变化，必须重建 frontend 镜像；后端 context 也变化，必须重建 backend。

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend maas sandbox postgres redis minio
```

健康检查：

```bash
curl -s http://localhost:8001/healthz
curl -I http://localhost:18080
```

期望：

- backend `status=ok`
- frontend HTTP 200 或 304

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

期望：能返回当前用户。

## 2. 准备一个可用知识库

优先复用 Step 1 已验证过的知识库：

```bash
KB_ID=$(curl -s http://localhost:8001/api/v1/kbs \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; rows=json.load(sys.stdin); print(rows[0]["id"] if rows else "")')

echo "KB_ID=$KB_ID"
```

确认该知识库至少有一个成功入库文档：

```bash
curl -s http://localhost:8001/api/v1/kbs/$KB_ID/documents \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：至少一条文档 `parse_status` 是 `done`。如果没有，先按 `docs/migration/07-step1-rag-verify.md` 的第 2.1 节上传 txt 并等到 `done`。

## 3. 浏览器创建智能体验证

打开：

```text
http://localhost:18080/agents
```

操作：

1. 强制刷新页面：`Cmd + Shift + R`
2. 切到“创建向导”
3. 选择模板或直接进入基础信息
4. 到“能力配置”步骤
5. 确认能看到：
   - “知识库”多选控件
   - “基础召回参数”折叠区
   - `TopK`
   - `Score Threshold`
   - `检索模式`
6. 选择一个知识库
7. 设置：
   - `TopK=3`
   - `Score Threshold=0`
   - `检索模式=混合`
8. 点击“创建并调试”

期望：

- 创建成功，不白屏。
- 右上角出现“智能体已创建”提示。
- 智能体列表中该智能体的绑定列显示 `1 KB / 0 工具` 或更多 KB 数量。
- 如果名称重复，页面应提示“智能体名称已存在，请换一个名称后重试。”，而不是点击后无反应。

建议本次新建时把智能体名称改成一个唯一名称，例如：

```text
step2-ui-agent-你的日期或时间
```

后面验证必须使用这个前端刚新建的智能体，不要使用旧的 Step1 智能体。

前端提交 body 的关键代码在 `frontend/src/views/AgentListView.vue`：

```ts
body: {
  name: form.value.name,
  type: form.value.type,
  template_id: form.value.template_id || null,
  model_id: form.value.model_id || null,
  persona: form.value.persona,
  kb_ids: form.value.kb_ids,
  tool_ids: [],
  config: {
    temperature: 0.2,
    rag: normalizeRagConfig(form.value.rag),
  },
}
```

这证明前端已经不再写死 `kb_ids: []`，并且会提交 `config.rag`。

## 4. 用 API 验证创建结果

把浏览器刚才新建的智能体名称填到变量里，必须精确匹配：

```bash
AGENT_NAME='step2-ui-agent-替换成你刚才输入的完整名称'
```

按名称精确取 ID：

```bash
AGENT_ID=$(curl -s http://localhost:8001/api/v1/agents \
  -H "Authorization: Bearer $ACCESS" \
  | AGENT_NAME="$AGENT_NAME" python3 -c 'import os,sys,json; rows=json.load(sys.stdin); name=os.environ["AGENT_NAME"]; matches=[x for x in rows if x["name"]==name]; assert len(matches)==1, f"expected exactly one agent named {name}, got {len(matches)}"; print(matches[0]["id"])')

echo "AGENT_ID=$AGENT_ID"
```

如果名称重复或你不确定，打开浏览器列表确认刚新建的智能体 ID 后手动设置：

```bash
AGENT_ID=<替换为你的智能体ID>
```

查看详情：

```bash
curl -s http://localhost:8001/api/v1/agents/$AGENT_ID \
  -H "Authorization: Bearer $ACCESS" \
  | tee /tmp/step2-agent.json \
  | python3 -m json.tool
```

检查绑定和 RAG 配置：

```bash
python3 - <<'PY'
import json, os
data=json.load(open("/tmp/step2-agent.json"))
print("kb_ids=", data.get("kb_ids"))
print("config.rag=", (data.get("config") or {}).get("rag"))
assert data.get("kb_ids"), "kb_ids is empty"
rag=(data.get("config") or {}).get("rag") or {}
assert rag.get("top_k") == 3, "config.rag.top_k is not 3"
assert rag.get("score_threshold") == 0, "config.rag.score_threshold is not 0"
assert rag.get("match_type") == "hybrid", "config.rag.match_type is not hybrid"
PY
```

期望：

- `kb_ids` 包含所选知识库。
- `config.rag.top_k=3`
- `config.rag.score_threshold=0`
- `config.rag.match_type=hybrid`

## 5. 编辑智能体回显和修改

浏览器操作：

1. 在智能体列表点击该智能体的“编辑”
2. 确认弹窗能回显：
   - 已选知识库
   - `TopK=3`
   - `Score Threshold=0`
   - `检索模式=混合`
3. 修改：
   - `TopK=1`
   - 保持知识库选中
4. 保存

API 验证：

```bash
curl -s http://localhost:8001/api/v1/agents/$AGENT_ID \
  -H "Authorization: Bearer $ACCESS" \
  | tee /tmp/step2-agent-updated.json \
  | python3 -m json.tool

python3 - <<'PY'
import json
data=json.load(open("/tmp/step2-agent-updated.json"))
rag=(data.get("config") or {}).get("rag") or {}
print("kb_ids=", data.get("kb_ids"))
print("config.rag=", rag)
assert data.get("kb_ids"), "kb_ids is empty after edit"
assert rag.get("top_k") == 1, "config.rag.top_k is not updated to 1"
PY
```

期望：

- 保存后 `kb_ids` 仍然有值。
- `config.rag.top_k` 更新为 1。

## 6. 验证 top_k 真透传到上下文

先发布智能体：

```bash
curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/publish \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

调用 context：

```bash
curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/context \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","max_tokens":3500}' \
  | tee /tmp/step2-context-top1.json \
  | python3 -m json.tool
```

检查采用的 RAG 配置和返回片段数：

```bash
python3 - <<'PY'
import json
data=json.load(open("/tmp/step2-context-top1.json"))
chunks=data.get("retrieved_chunks") or []
rag=(data.get("truncation") or {}).get("rag") or {}
messages="\n".join(m.get("content","") for m in data.get("messages", []))
print("retrieved_chunks=", len(chunks))
print("truncation.rag=", rag)
print("has_knowledge_message=", "知识片段" in messages)
assert rag.get("top_k") == 1, "context did not use config.rag.top_k=1"
assert len(chunks) <= 1, "retrieved_chunks exceeded top_k=1"
assert "知识片段" in messages, "knowledge was not injected"
PY
```

期望：

- `truncation.rag.top_k=1`
- `retrieved_chunks <= 1`
- messages 中有 “知识片段”
- 这个请求体没有传 `top_k`，因此能证明后端读取的是 `agent.config.rag.top_k=1`。

再把 `TopK` 改回 3，重复本节检查。这里用 API 改回 3，也可以在浏览器编辑弹窗里改：

```bash
curl -s -X PATCH http://localhost:8001/api/v1/agents/$AGENT_ID \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"config":{"temperature":0.2,"rag":{"top_k":3,"score_threshold":0,"match_type":"hybrid"}}}' \
  | python3 -m json.tool

curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/context \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","max_tokens":3500}' \
  | tee /tmp/step2-context-top3.json \
  | python3 -m json.tool
```

检查：

```bash
python3 - <<'PY'
import json
data=json.load(open("/tmp/step2-context-top3.json"))
chunks=data.get("retrieved_chunks") or []
rag=(data.get("truncation") or {}).get("rag") or {}
messages="\n".join(m.get("content","") for m in data.get("messages", []))
print("retrieved_chunks=", len(chunks))
print("truncation.rag=", rag)
print("has_knowledge_message=", "知识片段" in messages)
assert rag.get("top_k") == 3, "context did not use config.rag.top_k=3"
assert len(chunks) <= 3, "retrieved_chunks exceeded top_k=3"
assert "知识片段" in messages, "knowledge was not injected"
PY
```

期望：

- `truncation.rag.top_k=3`
- 有可用知识时，`retrieved_chunks` 最多 3 条。

显式请求覆盖验证：

```bash
curl -s -X POST http://localhost:8001/api/v1/agents/$AGENT_ID/context \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","max_tokens":3500,"top_k":1}' \
  | tee /tmp/step2-context-explicit-top1.json \
  | python3 -m json.tool

python3 - <<'PY'
import json
data=json.load(open("/tmp/step2-context-explicit-top1.json"))
rag=(data.get("truncation") or {}).get("rag") or {}
chunks=data.get("retrieved_chunks") or []
print("retrieved_chunks=", len(chunks))
print("truncation.rag=", rag)
assert rag.get("top_k") == 1, "explicit request top_k=1 did not override agent config"
assert len(chunks) <= 1, "retrieved_chunks exceeded explicit top_k=1"
PY
```

期望：

- 当前 agent 配置是 `top_k=3`，但请求体显式传了 `top_k=1`，所以 `truncation.rag.top_k` 必须是 1。

## 7. 回归 Step 1 链路

检索回归：

```bash
curl -s -X POST http://localhost:8001/api/v1/kbs/$KB_ID/retrieve \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","top_k":2}' \
  | python3 -m json.tool
```

SSE 回归：

```bash
curl -N -s -X POST http://localhost:8001/api/v1/chat \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$AGENT_ID\",\"query\":\"合同审批要注意什么？\",\"max_tool_rounds\":0}" \
  | tee /tmp/step2-chat.sse

grep -n "event: citation" /tmp/step2-chat.sse
grep -n "event: done" /tmp/step2-chat.sse
```

期望：

- 知识库检索仍返回 `content/snippet`
- SSE 仍有 `citation` 和 `done`
- 智能体列表绑定数量显示正确
