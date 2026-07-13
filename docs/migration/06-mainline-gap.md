# 06 主线能力盘点：智能体 + RAG + 发布 API

目标主线：

> 用户能自己创建智能体 -> 给智能体挂知识库 RAG -> 把这个智能体发布成对外 API（带 API Key）-> 外部用 API Key 调用它并得到基于知识库的回答。

本文件只做 Step 0 盘点和施工计划，不写业务代码。

## 1. 建智能体现状

### 我们现在有什么

- 后端已有智能体模板、模型下拉、智能体 CRUD、发布、上下文构建、运行接口：
  - `backend/app/api/v1/agents.py:42` `GET /agent-templates`
  - `backend/app/api/v1/agents.py:54` `GET /models`，这是老接口，仍给智能体创建页下拉用
  - `backend/app/api/v1/agents.py:63` `GET /agents`
  - `backend/app/api/v1/agents.py:72` `POST /agents`
  - `backend/app/api/v1/agents.py:108` `PATCH /agents/{agent_id}`
  - `backend/app/api/v1/agents.py:135` `POST /agents/{agent_id}/publish`
  - `backend/app/api/v1/agents.py:158` `POST /agents/{agent_id}/context`
  - `backend/app/api/v1/agents.py:184` `POST /agents/{agent_id}/run`
- 智能体创建/更新 schema 已支持模型、知识库、工具绑定：
  - `backend/app/schemas/agents.py:23` `AgentCreate` 包含 `model_id/kb_ids/tool_ids`
  - `backend/app/schemas/agents.py:37` `AgentUpdate` 包含 `model_id/kb_ids/tool_ids`
- 服务层会校验并保存绑定关系：
  - `backend/app/services/agent_service.py:26` 创建时合并模板配置、校验模型和绑定
  - `backend/app/services/agent_service.py:52` 创建后调用 `replace_kbs/replace_tools`
  - `backend/app/services/agent_service.py:103` 更新时可替换 `kb_ids`
  - `backend/app/repositories/agent_repository.py:20` `replace_kbs`
  - `backend/app/repositories/agent_repository.py:30` `get_kb_ids`
- 运行时能跑一次智能体对话：
  - `backend/app/orchestrator/runtime.py:34` `run_agent`
  - `backend/app/orchestrator/runtime.py:55` 调用 `build_agent_context`
  - `backend/app/orchestrator/runtime.py:104` 调用 MaaS chat
  - `backend/app/orchestrator/runtime.py:143` assistant message 会保存 citations
- 前端智能体工厂能创建、发布、显示已有 KB/工具绑定数量，但创建表单没有让用户选知识库：
  - `frontend/src/views/AgentListView.vue:29` 加载 `/agents`
  - `frontend/src/views/AgentListView.vue:31` 加载老 `/models`
  - `frontend/src/views/AgentListView.vue:50` `createAgent`
  - `frontend/src/views/AgentListView.vue:58` 提交 `model_id`
  - `frontend/src/views/AgentListView.vue:59` 固定提交 `kb_ids: []`
  - `frontend/src/views/AgentListView.vue:117` 列表能显示 `KB / 工具` 数量
  - `frontend/src/views/AgentListView.vue:82` 调 `/agents/{id}/publish`

### 结论

后端已经具备“创建智能体 + 绑模型 + 绑知识库 + 跑对话”的基础能力；前端只完成了“创建智能体 + 选模型 + 发布”，还没有把“选择知识库/召回参数”交给用户配置。因此主线第一环节后端可用，前端不完整。

## 2. 挂知识库 RAG 现状与已知问题排查

### 知识库与入库

- 数据模型：
  - `backend/app/models/entities.py:75` `KnowledgeBase`
  - `backend/app/models/entities.py:96` `Document`
  - `backend/app/models/entities.py:116` `Chunk`
  - `backend/app/models/entities.py:180` `Agent`
  - `backend/app/models/entities.py:200` `AgentKb`
- 知识库 API：
  - `backend/app/api/v1/kbs.py:26` `GET /kbs`
  - `backend/app/api/v1/kbs.py:34` `POST /kbs`
  - `backend/app/api/v1/kbs.py:66` `GET /kbs/{kb_id}`
  - `backend/app/api/v1/kbs.py:78` `PATCH /kbs/{kb_id}`
  - `backend/app/api/v1/kbs.py:108` `DELETE /kbs/{kb_id}` 目前是归档
  - `backend/app/api/v1/kbs.py:132` `POST /kbs/{kb_id}/documents`
  - `backend/app/api/v1/kbs.py:169` `GET /kbs/{kb_id}/documents`
  - `backend/app/api/v1/kbs.py:183` `POST /kbs/{kb_id}/retrieve`
- 入库链路：
  - `backend/app/services/kb_service.py:65` 上传文件到对象存储并创建 `Document`
  - `backend/app/rag/tasks.py:7` 后台执行解析任务
  - `backend/app/rag/ingest.py:23` 下载文档、解析文本、切片、向量化
  - `backend/app/rag/ingest.py:44` 写入 `Chunk.content` 和 `Chunk.embedding`
  - `backend/app/rag/chunking.py:9` 按段落窗口切片
  - `backend/app/rag/parsers.py:7` 支持 txt/md/pdf/docx
  - `backend/app/rag/embeddings.py:7` 调 MaaS `/v1/embeddings`
- 检索链路：
  - `backend/app/rag/retrieve.py:33` `retrieve_chunks`
  - `backend/app/rag/retrieve.py:75` vector search 查询 `Chunk.content`
  - `backend/app/rag/retrieve.py:115` text search 查询 `Chunk.content`
  - `backend/app/rag/retrieve.py:45` 返回 `RetrievedChunkOut(content=...)`
  - `backend/app/rag/retrieve.py:57` 返回 `CitationOut(snippet=...)`
  - `backend/app/schemas/kb.py:81` `RetrievedChunkOut` 明确包含 `content`
  - `backend/app/schemas/kb.py:91` `CitationOut` 明确包含 `snippet`

### 智能体对话是否注入知识库

- `backend/app/orchestrator/context.py:39` 读取 agent 绑定 KB 和 workspace KB
- `backend/app/orchestrator/context.py:48` 调 `retrieve_agent_knowledge`
- `backend/app/orchestrator/context.py:130` 对多个知识库逐个调用 `retrieve_chunks`
- `backend/app/orchestrator/context.py:144` 按分数截取 top_k
- `backend/app/orchestrator/context.py:238` `fit_knowledge`
- `backend/app/orchestrator/context.py:258` 把 `chunk.content` 拼成 “知识片段”
- `backend/app/orchestrator/context.py:273` 返回 system message
- `backend/app/orchestrator/runtime.py:103` 将 `context.messages` 传给 MaaS

结论：后端运行时已经会把命中的知识片段注入模型上下文。真正风险不是“后端完全没注入”，而是“用户创建智能体时没有绑定知识库”或“前端展示/构建版本没有体现片段”。

### “检索返回 2 条但看不到内容”的根因判断

从当前源码看：

- 不是检索层没有返回正文：`backend/app/rag/retrieve.py:45` 返回 `content`
- 不是 schema 没暴露正文：`backend/app/schemas/kb.py:81` `RetrievedChunkOut.content`
- 不是 context 没注入知识：`backend/app/orchestrator/context.py:258` 使用 `chunk.content`
- 当前知识库前端源码已经有结果面板：
  - `frontend/src/views/KnowledgeBaseListView.vue:17` 保存 `retrieveResult`
  - `frontend/src/views/KnowledgeBaseListView.vue:57` 调 `/kbs/{id}/retrieve`
  - `frontend/src/views/KnowledgeBaseListView.vue:179` 展示 `chunk.content || chunk.snippet || citation.snippet`

因此，如果浏览器仍只看到“检索完成，返回 2 条片段”而看不到内容，最可能是运行中的前端镜像仍是旧构建，或者当前页面此前只做了 toast/提示没有渲染结果列表。Step 1 需要先用真实浏览器和 curl 双重确认：接口返回内容、前端 dist 也展示内容；如果 dist 不是最新，则只重建前端；如果仍不展示，再修展示层。

### 对话工作台引用展示

- `backend/app/api/v1/chat.py:19` `/chat` 是 SSE 对话接口
- `backend/app/api/v1/chat.py:111` 会先发 `citation` 事件
- `frontend/src/views/ChatWorkbenchView.vue:69` 调 `/chat`
- `frontend/src/views/ChatWorkbenchView.vue:96` 接收 `citation`
- `frontend/src/views/ChatWorkbenchView.vue:186` 展示引用卡片

## 3. 发布成 API 现状与 wanwu 差距

### 我们现在有什么

- 后端只有“把智能体状态置为 active”的发布动作：
  - `backend/app/api/v1/agents.py:135` `POST /agents/{agent_id}/publish`
  - `backend/app/services/agent_service.py:116` `publish_agent` 只设置 `agent.status = "active"`
- 发布中心前端是静态渠道卡片：
  - `frontend/src/views/PublishCenterView.vue:20` 只读取 `/agents`
  - `frontend/src/views/PublishCenterView.vue:11` 静态声明 Web/iframe/API Key/机器人渠道
  - `frontend/src/views/PublishCenterView.vue:43` “发布新版本”按钮没有绑定真实接口
  - `frontend/src/views/PublishCenterView.vue:53` 渠道卡片是静态渲染
- 数据模型已有很薄的 `ApiKey` 表，但没有服务/API 使用它：
  - `backend/app/models/entities.py:236` `ApiKey`
  - 字段只有 `tenant_id/name/key_hash/scopes/status`
  - `rg` 未发现 `api_keys` 对应 CRUD router/service
- 没有 App/Application/PublishedApp/AppKey 这样的发布产物表。

### wanwu app-service 设计可参考的能力

`wanwu/proto/app-service/app-service.proto` 将能力分成：

- API Key 管理：
  - `CreateApiKey/ListApiKeys/UpdateApiKey/UpdateApiKeyStatus/DeleteApiKey/GetApiKeyByKey`
  - `CreateApiKeyReq` 包含 `name/desc/expiredAt/userId/orgId`
  - `ApiKeyInfo` 包含 `keyId/key/userId/name/desc/expiredAt/createdAt/status/orgId`
- AppKey 管理：
  - `GenAppKey/GetAppKeyList/DelAppKey/GetAppKeyByKey`
  - `GenAppKeyReq` 包含 `appId/appType/userId/orgId`
  - `AppKeyInfo` 包含 `appKeyId/appKey/userId/orgId/appId/appType/createdAt`
- App 发布：
  - `PublishApp/UnPublishApp/GetAppList/GetAppInfo/DeleteApp`
  - `PublishAppReq` 包含 `appId/appType/publishType/userId/orgId`
  - `AppInfo` 包含 `appId/appType/createdAt/publishType/userId/orgId`
- URL 渠道：
  - `AppUrlCreate/AppUrlUpdate/AppUrlDelete/GetAppUrlList/GetAppUrlInfoBySuffix/AppUrlStatusSwitch`
- 统计：
  - `GetAppStatistic/RecordAppStatistic/GetAppStatisticList`
  - `GetAPIKeyStatistic/GetAPIKeyStatisticList/GetAPIKeyStatisticRecord/RecordAPIKeyStatistic`

### 结论

我们现在只有“内部 active 状态”，没有“发布版本/渠道/AppKey/API Key/过期时间/状态切换/调用统计”的应用发布层。主线需要补一个最小发布层，不能只复用 `agent.status=active`。

## 4. 外部调用现状

### 我们现在有什么

- 内部 JWT 对话：
  - `backend/app/api/v1/chat.py:19` `POST /api/v1/chat`，需要用户 JWT
  - `backend/app/api/v1/agents.py:184` `POST /api/v1/agents/{agent_id}/run`，需要用户 JWT
  - `backend/app/core/auth.py:57` `get_current_auth` 解析 JWT
- MaaS 模型级 OpenAI 兼容调用：
  - `backend/app/orchestrator/runtime.py:275` 内部调用 MaaS `/v1/chat/completions`
  - MaaS 是模型服务入口，输入是 model/messages，不知道 agent/kb/publish/api key。

### 缺口

没有一个“外部调用已发布智能体”的接口，例如：

```text
POST /api/v1/public/agents/{agent_id}/chat
Authorization: Bearer <app_api_key>
```

这个接口需要：

- 用 API Key 找到租户和已发布智能体
- 校验 key 状态、过期时间、scope、绑定 agent
- 调用现有 `dispatch_single_agent`
- 返回 answer + citations
- 记录 UsageRecord / API Key 调用记录

## 5. 主线 Gap 表

| 环节 | 现状 | 差距 | 本次要补 | 留占位 |
|---|---|---|---|---|
| 1. 用户创建智能体 | 后端支持 `model_id/kb_ids/tool_ids`，能创建/更新/发布/运行；前端创建页只选模型，固定 `kb_ids: []` | 用户不能在创建/编辑页自然选择知识库；召回参数无入口 | 前端添加知识库选择；后端保持现有绑定；在 agent config 中落基础 RAG 参数 | 多智能体编排、复杂工具路由、审批发布流 |
| 2. 挂知识库 RAG | 有 KB/Document/Chunk、上传解析、向量+关键词混合检索；运行时会注入知识片段 | 前端/构建版本可能导致命中内容不可见；创建智能体默认不绑定 KB；召回策略只有 top_k | 先确认并修好命中内容展示；在智能体配置中加入 topK/threshold/matchType 基础项 | GraphRAG、rerankModelId、父子分段配置 UI、切片可视化编辑、标注审核、多模态解析 |
| 3. 发布成 API | agent publish 只是 `status=active`；发布中心是静态渠道卡 | 没有发布版本、发布渠道、AppKey、API Key 生成、过期/启停 | 新增最小发布产物表和 API Key 生成接口；发布中心接真实接口 | Web URL 渠道、iframe 域名白名单、机器人渠道、灰度版本、发布 diff 完整审计 |
| 4. 外部调用 | 内部 JWT `/chat` 和 `/agents/{id}/run` 可跑智能体；MaaS `/v1/chat` 是模型级 | 没有 API Key 鉴权的智能体级外部调用 | 新增外部智能体调用接口，复用 `dispatch_single_agent`，返回答案+引用 | 计费套餐、限流网关、IP 白名单、调用明细看板、OpenAI Assistant 兼容格式 |

## 6. 分步施工计划

### Step 1：修好 RAG 可见性与知识注入地基

目标：让“知识库命中测试”和“智能体挂知识库后对话”都能看到命中片段/引用，并确认知识片段真的进入上下文。

预计改动文件：

- 可能需要：`frontend/src/views/KnowledgeBaseListView.vue`
- 可能需要：`frontend/src/views/ChatWorkbenchView.vue`
- 可能需要：`frontend/src/api/types.ts`
- 如果发现后端返回不完整才动：`backend/app/schemas/kb.py`、`backend/app/rag/retrieve.py`、`backend/app/orchestrator/context.py`
- 新增验证文档：`docs/migration/07-step1-rag-visible-verify.md`

本地验证：

```bash
docker compose up -d --build backend frontend maas sandbox postgres redis minio

ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

KB_ID=$(curl -s http://localhost:8001/api/v1/kbs \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["id"])')

curl -s -X POST "http://localhost:8001/api/v1/kbs/$KB_ID/retrieve" \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同 审批","top_k":2}' \
  | python3 -m json.tool
```

验收点：

- `chunks[0].content` 有正文
- `citations[0].snippet` 有摘要
- 浏览器 `http://localhost:18080/kbs` 能看到命中片段正文
- 绑定该 KB 的 active agent 调 `/api/v1/agents/{agent_id}/context` 时，`retrieved_chunks` 非空，`messages` 中有 “知识片段”
- 调 `/api/v1/chat` 时 SSE 返回 `citation` 事件

### Step 2：智能体绑定知识库与基础召回配置

目标：用户在创建/编辑智能体时可以选择知识库，并配置基础召回参数。

预计改动文件：

- `frontend/src/views/AgentListView.vue`
- `frontend/src/api/types.ts`
- `backend/app/schemas/agents.py`
- `backend/app/services/agent_service.py`
- `backend/app/orchestrator/context.py`
- 可能新增迁移：给 agent config 使用 JSON，不一定需要新列
- 新增验证文档：`docs/migration/08-step2-agent-kb-config-verify.md`

建议第一批只实现：

- 选择多个知识库 `kb_ids`
- `top_k`
- `score_threshold`
- `match_type`: `hybrid/vector/keyword`

先不实现：

- rerank 模型、GraphRAG、复杂 meta filter、父子分段策略 UI。

本地验证：

```bash
docker compose up -d --build backend frontend

# 登录拿 ACCESS 后：
curl -s -X POST http://localhost:8001/api/v1/agents \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"mainline-rag-agent","type":"qa","model_id":"<MODEL_ID>","kb_ids":["<KB_ID>"],"tool_ids":[],"config":{"rag":{"top_k":3,"score_threshold":0.2,"match_type":"hybrid"}}}'

curl -s -X POST http://localhost:8001/api/v1/agents/<AGENT_ID>/publish \
  -H "Authorization: Bearer $ACCESS"

curl -s -X POST http://localhost:8001/api/v1/agents/<AGENT_ID>/context \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？","top_k":3}' \
  | python3 -m json.tool
```

### Step 3：发布 + API Key 生成

目标：把一个智能体发布成可对外调用的应用，并生成只展示一次的 API Key。

预计改动文件：

- 新迁移：新增发布产物表，例如 `published_apps` / `app_keys`，或扩展现有 `api_keys`
- `backend/app/models/entities.py`
- `backend/app/schemas/publish.py`
- `backend/app/services/publish_service.py`
- `backend/app/api/v1/publish.py`
- `backend/app/main.py`
- `frontend/src/views/PublishCenterView.vue`
- `frontend/src/api/types.ts`
- 新增验证文档：`docs/migration/09-step3-publish-apikey-verify.md`

最小字段建议：

- `published_apps`: `tenant_id/agent_id/name/status/publish_type/version/config/created_by/created_at/updated_at`
- `app_api_keys`: `tenant_id/app_id/name/key_hash/key_prefix/scopes/status/expires_at/created_by/created_at/last_used_at`

本地验证：

```bash
docker compose up -d --build backend frontend
docker compose exec backend alembic upgrade head

curl -s -X POST http://localhost:8001/api/v1/published-apps \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"<AGENT_ID>","publish_type":"api","name":"mainline-api"}'

curl -s -X POST http://localhost:8001/api/v1/published-apps/<APP_ID>/keys \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"name":"mainline-test-key"}'
```

验收点：

- 返回明文 key 只出现一次
- 列表只显示 `key_prefix`，不显示明文和 hash
- key 可停用/启用
- 发布中心能看到 API Key 渠道已开启。

### Step 4：外部智能体级调用接口

目标：外部系统拿 API Key 调用已发布智能体，走完整 RAG 问答，返回答案和引用。

预计改动文件：

- `backend/app/core/auth.py` 或新增 `backend/app/core/api_key_auth.py`
- `backend/app/api/v1/public_agents.py`
- `backend/app/schemas/public_chat.py`
- `backend/app/services/publish_service.py`
- `backend/app/orchestrator/runtime.py` 可能只复用，不改
- `backend/app/main.py`
- 新增验证文档：`docs/migration/10-step4-public-agent-api-verify.md`

接口建议：

```text
POST /api/v1/public/apps/{app_id}/chat
Authorization: Bearer <app_api_key>
```

请求：

```json
{
  "query": "合同审批要注意什么？",
  "conversation_id": null,
  "stream": false
}
```

响应：

```json
{
  "answer": "...",
  "citations": [
    {"doc_name": "...", "snippet": "...", "score": 0.03}
  ],
  "conversation_id": "...",
  "usage": {}
}
```

本地验证：

```bash
curl -s -X POST http://localhost:8001/api/v1/public/apps/<APP_ID>/chat \
  -H "Authorization: Bearer <APP_API_KEY>" \
  -H 'Content-Type: application/json' \
  -d '{"query":"合同审批要注意什么？"}' \
  | python3 -m json.tool
```

验收点：

- 不需要用户 JWT
- 停用 key 后返回 401/403
- 未发布/停用 app 不可调用
- 返回 answer + citations
- 写入调用记录或至少 UsageRecord。

## 7. 本批次边界

### 本批次必须跑通的最小能力

- 用户在前端创建智能体时能选择模型和知识库
- 知识库检索结果能看到正文和来源
- 智能体对话能基于绑定知识库回答，并展示引用
- 发布中心能为某个智能体生成 API Key
- 外部系统能用 API Key 调用这个智能体，得到答案和引用

### 明确放到后续批次

- GraphRAG / 知识图谱
- rerank 模型接入和模型选择
- 父子分段、合并拆分、切片可视化编辑
- 标注审核、人工反馈闭环
- 多模态解析
- URL 导入、网页抓取、定时重解析
- Web 分享页和 iframe 渠道完整治理
- 机器人渠道（钉钉、企微）
- API 网关级限流、IP 白名单、配额计费
- 完整发布 diff、灰度版本、回滚审批流
