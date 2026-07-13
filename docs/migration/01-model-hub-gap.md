# Model Hub Capability Gap

本文件是第 0 步产物：只对齐 Wanwu 模型纳管契约与当前 Python 工程现状，不实现业务代码。

说明：当前仓库没有独立的 `legacy/backend` 目录。现有后端能力实际分布在 `backend/` 和 `maas/` 两个 Python 服务中，因此本文用这两个目录代表当前 legacy 后端能力。

## 1. Wanwu 模型纳管契约

来源：`wanwu/proto/model-service/model-service.proto`

### 1.1 模型管理操作

| Wanwu RPC | 产品语义 | 当前迁移判断 |
|---|---|---|
| `ImportModel(ModelInfo)` | 导入模型 | 本次要补，映射为创建逻辑模型 + 默认渠道配置 |
| `UpdateModel(ModelInfo)` | 更新导入模型 | 本次要补，先支持可落地字段 |
| `DeleteModel(DeleteModelReq)` | 删除模型 | 本次要补软删除/禁用，不做物理删除 |
| `ChangeModelStatus(ModelStatusReq)` | 模型启用/关闭 | 本次要补，映射到模型状态；渠道仍保留独立状态 |
| `GetModel(GetModelReq)` | 按 modelId 查询单个模型 | 本次要补 |
| `GetModelByUuid(GetModelByUuidReq)` | 按 uuid 查询模型 | 本次留占位；我们当前主键已经是 UUID，暂不引入双 ID |
| `ListModels(ListModelsReq)` | 模型列表，支持类型、供应商、状态、显示名、作用域过滤 | 本次要补基础过滤；作用域先保留字段 |
| `ListModelsByIds(ListModelsByIdsReq)` | 按 ID 批量查询 | 本次可补 |
| `ListModelsByUuids(ListModelsByUuidsReq)` | 按 UUID 批量查询 | 本次留占位，同 `GetModelByUuid` |
| `ListTypeModels(ListTypeModelsReq)` | 按模型类型列出 llm/rerank/embedding | 本次要补，先复用列表过滤 |
| `ListModelsInStatisticScope(ListModelsInStatisticScopeReq)` | 统计看板按 org/user scope 批量查询模型 | 本次留占位；统计看板暂不依赖 |

### 1.2 模型字段

| Wanwu 字段 | 语义 | 本次处理 |
|---|---|---|
| `userId` | 创建/归属用户 | 可实现：映射当前认证用户 |
| `orgId` | 组织/租户 | 可实现：映射当前 `tenant_id` |
| `modelId` | 模型业务 ID | 可实现：映射当前 `models.id` |
| `provider` | 模型供应商 | 已有，需纳入接口 |
| `modelType` | 模型类型 | 已有，字段名为 `type`；需统一 API 命名 |
| `model` | 上游真实模型名/逻辑模型名 | 已有，当前字段名为 `name` |
| `displayName` | 页面显示名 | 本次要补 |
| `modelIconPath` | 模型图标路径 | 本次留占位列，不实现上传/静态资源管理 |
| `publishDate` | 发布时间 | 本次留占位列，不驱动逻辑 |
| `isActive` | 模型启用状态 | 本次要补 |
| `providerConfig` | 供应商扩展配置 | 本次要补 JSON 占位；只保存，不解释复杂 provider schema |
| `createdAt` | 创建时间 | 部分已有：`model_channels.created_at` 有；`models` 当前没有 |
| `updatedAt` | 更新时间 | 本次要补 |
| `modelDesc` | 模型描述 | 本次要补 |
| `uuid` | 额外 UUID | 留占位；当前主键就是 UUID，不引入第二套 ID |
| `scopeType` | 公开范围，私有/公开/组织 | 本次留占位列；先默认组织/租户内可见 |
| `importSource` | 导入来源，builtin/external | 本次要补，默认 `external`，seed/mock 可标记 `builtin` |

### 1.3 模型体验对话

| Wanwu RPC/字段 | 语义 | 本次处理 |
|---|---|---|
| `SaveModelExperienceDialog` | 保存模型体验会话 | 第二阶段实现，不放进第 1 个最小闭环 |
| `GetModelExperienceDialog` | 查询单个体验会话 | 第二阶段 |
| `GetModelExperienceDialogs` | 查询体验会话列表 | 第二阶段 |
| `DeleteModelExperienceDialog` | 删除体验会话 | 第二阶段 |
| `SaveModelExperienceDialogRecord` | 保存体验消息记录 | 第二阶段 |
| `GetModelExperienceDialogRecords` | 查询体验消息记录 | 第二阶段 |
| `modelSetting` | 体验参数配置 | 第二阶段，建议 JSON |
| `originalContent` / `handledContent` / `reasoningContent` | 原始内容、处理后内容、思考内容 | 第二阶段；先不强行塞进现有 chat 表 |
| `fileInfo` | 体验文件信息 | 占位；本次不实现文件上传体验 |

## 2. 当前 Python 工程已有能力

### 2.1 数据表与模型

| 当前能力 | 证据路径 | 说明 |
|---|---|---|
| 已有 `models` 表 | `backend/alembic/versions/202607070001_init_data_layer.py` | 字段：`id`、`name`、`provider`、`type` |
| 已有 `model_channels` 表 | `backend/alembic/versions/202607070001_init_data_layer.py` | 字段：`tenant_id`、`model_id`、`base_url`、`api_key_enc`、`weight`、`rpm_limit`、`status`、`health`、`created_at` |
| SQLAlchemy ORM 已声明 `Model` | `backend/app/models/entities.py` | 字段：`name`、`provider`、`type` |
| SQLAlchemy ORM 已声明 `ModelChannel` | `backend/app/models/entities.py` | 字段与迁移基本一致 |
| MaaS 也有 Core Table 版本 | `maas/app/models.py` | `models`、`model_channels`、`usage_records`、`api_keys` 以 SQLAlchemy Table 形式声明 |
| 当前没有模型唯一性迁移增强 | `backend/alembic/versions/202607080001_add_name_uniqueness.py` | 已处理智能体/知识库/工具/工作空间/文档/用户名称唯一性，但没有处理 `models` |

### 2.2 MaaS 渠道与调用能力

| 当前能力 | 证据路径 | 说明 |
|---|---|---|
| 创建渠道时会自动 ensure 模型 | `maas/app/services.py` | `ensure_model()` 根据模型名创建 `models` 行 |
| 支持渠道创建/列表/详情/更新/禁用 | `maas/app/api/admin.py` | `/admin/channels` 系列接口 |
| 渠道密钥加密保存 | `maas/app/services.py` | `create_channel()` 使用 `encrypt_secret(payload.api_key)` 写入 `api_key_enc` |
| 支持渠道状态与健康状态 | `maas/app/schemas.py`、`maas/app/services.py` | `status` 为 `active/disabled`，`health` 为 `unknown/ok/failed` |
| 支持 OpenAI 兼容模型列表 | `maas/app/api/openai.py` | `GET /v1/models` 返回逻辑模型 |
| 支持 OpenAI 兼容 chat/embedding | `maas/app/api/openai.py` | `/v1/chat/completions`、`/v1/embeddings` |
| 支持按权重选择可用渠道 | `maas/app/services.py` | `weighted_choice()`、`list_candidate_channels()` |
| 支持 RPM 限流与用量记录 | `maas/app/services.py`、`maas/app/models.py` | `consume_rpm()`、`record_usage()`、`usage_records` |

### 2.3 Backend 对前端暴露能力

| 当前能力 | 证据路径 | 说明 |
|---|---|---|
| 有 `/api/v1/models` 列表接口 | `backend/app/api/v1/agents.py` | 目前只返回全部模型，按 `type/name` 排序 |
| 模型响应 schema 很薄 | `backend/app/schemas/agents.py` | `ModelOut` 只有 `id/name/provider/type` |
| 智能体创建可绑定模型 | `frontend/src/views/AgentListView.vue` | 页面调用 `/models`，在创建智能体时传 `model_id` |
| 智能体运行会通过模型名调用 MaaS | `backend/app/orchestrator/runtime.py` | 加载 `Model` 后用 `model.name` 调用 MaaS |

## 3. Gap 表

| 能力/字段 | Wanwu 有 | 我们当前有 | 差距 | 本次处理 |
|---|---|---|---|---|
| 模型导入 | 有 `ImportModel` | MaaS 可通过创建渠道隐式创建模型 | 没有正式模型导入 API；模型与渠道概念混在一起 | 补正式模型 API；首版可同时创建默认渠道 |
| 模型更新 | 有 `UpdateModel` | 只有渠道更新 | 无法改显示名、描述、导入来源等模型元信息 | 补 PATCH 模型 |
| 模型删除 | 有 `DeleteModel` | 只有渠道禁用 | 无模型级禁用/删除 | 补软删除/禁用，先不物理删除 |
| 模型启停 | 有 `ChangeModelStatus` | 渠道有 `status`，模型无状态 | 模型级状态缺失 | 补 `is_active` |
| 单模型详情 | 有 `GetModel` | Backend 无单模型详情；MaaS 有渠道详情 | 模型详情无法独立查看 | 补 GET `/models/{id}` |
| 模型列表过滤 | 按类型、供应商、启用状态、显示名、作用域 | Backend 只列全部 | 缺过滤和分页 | 补基础过滤；分页可先轻量实现 |
| 批量 ID 查询 | 有 | 无 | 前端/工作空间批量展示后续会需要 | 可补 |
| UUID 别名查询 | 有 | 主键就是 UUID | 无需双 UUID | 留占位，不实现 |
| 统计 scope 查询 | 有 | 用量记录有基础表，但无 scope 查询 | 看板暂不依赖 | 留占位 |
| `provider` | 有 | 有 | 需要统一到管理接口 | 本次纳入 |
| `modelType` | 有 | 有 `type` | 字段名不同 | API 用 `model_type`，DB 仍可用 `type` 或迁移别名 |
| `model` | 有 | 有 `name` | 字段名不同 | API 可用 `model` 或 `name`，文档明确 |
| `displayName` | 有 | 无 | 前端只能显示内部名 | 本次补 |
| `modelIconPath` | 有 | 无 | 暂无模型图标系统 | 占位列 + TODO |
| `publishDate` | 有 | 无 | 暂无发布生命周期 | 占位列 + TODO |
| `isActive` | 有 | 无模型级状态 | 只能禁用渠道，不能禁用模型 | 本次补 |
| `providerConfig` | 有 | 无 | 不支持供应商扩展配置 | 本次补 JSON 占位，只保存 |
| `createdAt/updatedAt` | 有 | 模型无，渠道有 `created_at` | 模型元信息无法排序审计 | 本次补 |
| `modelDesc` | 有 | 无 | 无说明文案 | 本次补 |
| `uuid` | 有 | `id` 已是 UUID | 不需要额外字段 | 留占位，不实现 |
| `scopeType` | 有 | `tenant_id` 在渠道上，不在模型上 | 模型级作用域不完整 | 占位列，默认租户可见 |
| `importSource` | 有 | 无 | 无法区分内置/外部导入 | 本次补 |
| 体验对话 | 有完整 dialog/record | 当前有智能体会话，不是模型体验 | 模型测试台缺失 | 第二阶段实现 |

## 4. 本次模型纳管首版范围

### 4.1 本次要补

- 模型元信息字段：`display_name`、`description`、`is_active`、`provider_config`、`import_source`、`created_at`、`updated_at`。
- 模型占位字段：`model_icon_path`、`publish_date`、`scope_type`，仅落库和返回，先不驱动逻辑。
- 模型列表/详情/创建/更新/启停接口。
- 创建模型时可选择同时创建一个默认 MaaS 渠道：`base_url`、`api_key`、`weight`、`rpm_limit`。
- API 返回不暴露 `api_key_enc`。
- 保持现有智能体运行逻辑不变：仍通过 `Model.name` 调 MaaS。

### 4.2 本次暂不做

- 模型体验对话与体验消息记录。
- 图标上传和静态资源管理。
- 独立 `uuid` 字段。
- 统计 scope 查询。
- 复杂 provider schema 校验。
- rerank、GraphRAG 等依赖后续模块的真实能力；只允许保留模型类型和占位字段。

## 5. 四步施工计划

### Step 1: 数据模型迁移

目标：补齐模型纳管所需字段，不改变现有 chat/agent 运行路径。

预计改动文件：

- `backend/app/models/entities.py`
- `backend/alembic/versions/<new>_model_hub_upgrade.py`
- `maas/app/models.py`
- 可能同步补充 `maas/app/schemas.py` 的输出字段，但不先改业务接口

本步验证：

- 本地执行迁移后，检查 `models` 表字段存在。
- 检查已有 `mock-chat`、`siyids测试模型` 等模型仍可列出。

### Step 2: 后端接口

目标：在 `backend` 侧提供模型纳管 API，复用 MaaS 现有渠道数据和加密能力。

预计改动文件：

- `backend/app/schemas/models.py` 或扩展 `backend/app/schemas/agents.py`
- `backend/app/services/model_service.py`
- `backend/app/api/v1/models.py`
- `backend/app/api/v1/__init__.py` 或 `backend/app/main.py`
- 必要时小幅调整 `maas/app/api/admin.py` / `maas/app/services.py`

接口草案：

- `GET /api/v1/model-hub/models`
- `POST /api/v1/model-hub/models`
- `GET /api/v1/model-hub/models/{model_id}`
- `PATCH /api/v1/model-hub/models/{model_id}`
- `POST /api/v1/model-hub/models/{model_id}/status`
- `GET /api/v1/model-hub/models/{model_id}/channels`

本步验证：

- 使用 `curl` 登录后创建一个 mock 模型。
- 列表可见。
- 启停后状态变化。
- 现有 `/api/v1/models` 不破坏。

### Step 3: 前端页面

目标：新增模型纳管页面，不影响当前智能体创建页的模型下拉。

预计改动文件：

- `frontend/src/router/index.ts`
- `frontend/src/layouts/MainLayout.vue`
- `frontend/src/api/types.ts`
- `frontend/src/views/ModelHubView.vue`
- 可能调整 `frontend/src/styles.css`

页面首版：

- 模型列表：显示名称、内部模型名、供应商、类型、启用状态、导入来源、渠道健康。
- 创建/编辑弹窗：基础信息 + 默认渠道信息。
- 启用/停用按钮。
- 不展示密钥明文。

本步验证：

- 前端可访问模型纳管页面。
- 创建模型后列表刷新。
- 智能体创建页仍能选择模型。

### Step 4: 联调验证

目标：证明 Wanwu 契约的首个能力闭环在我们 Python 工程里跑通。

验证路径：

1. 创建模型 `model-hub-test`，provider=`mock`，type=`llm`，渠道 `mock://local`。
2. 在模型纳管页看到模型。
3. 创建智能体选择该模型。
4. 调试对话能返回 mock 响应。
5. 停用模型后，模型纳管页显示停用；后端拒绝新绑定或运行时给出清晰错误。

预计涉及文件：

- 后端测试脚本或验收 curl 文档：`docs/migration/01-model-hub-verify.md`
- 若需要，补少量接口测试。

## 6. 第 0 步本地验证命令

只验证本文档存在且当前没有改业务代码：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

test -f docs/migration/01-model-hub-gap.md && echo "gap doc ok"

grep -n "Model Hub Capability Gap" docs/migration/01-model-hub-gap.md
grep -n "Step 1: 数据模型迁移" docs/migration/01-model-hub-gap.md
```

如果你想顺手确认当前模型列表仍然可用：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8001/api/v1/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

