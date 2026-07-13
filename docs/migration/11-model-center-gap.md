# 11 模型中心 Gap：模型目录 + 一键接入闭环

目标：

> 把已完成的模型纳管扩展成“模型中心”：公共模型目录、预置接入配置、一键接入、连接测试，最终让新接入模型能被智能体选择使用。

本步骤只做 Step 0 盘点和计划，不写业务代码。

## 1. 现有模型纳管能力

### 1.1 数据模型

当前运行态模型数据已经落在两张表：

- `models`：逻辑模型。
  - 证据：`backend/app/models/entities.py:205` `class Model`
  - 字段包括 `name/provider/type/display_name/description/is_active/provider_config/import_source/model_icon_path/publish_date/scope_type/created_at/updated_at`
  - Step1 迁移证据：`backend/alembic/versions/202607100001_model_hub_metadata.py`
- `model_channels`：模型调用渠道。
  - 证据：`backend/app/models/entities.py:224` `class ModelChannel`
  - 字段包括 `tenant_id/model_id/base_url/api_key_enc/weight/rpm_limit/status/health/created_at`
  - `api_key_enc` 只保存加密密文，不保存明文。

MaaS 服务使用同一套物理表，但用 SQLAlchemy Table 定义：

- `maas/app/models.py:18` `models = Table(...)`
- `maas/app/models.py:39` `model_channels = Table(...)`

结论：模型中心必须复用现有 `models/model_channels`，不需要另建运行态模型表。

### 1.2 后端模型纳管 API

后端已有 `/api/v1/model-hub/models` 模型纳管接口：

- 列表：`backend/app/api/v1/models.py:33`
- 创建：`backend/app/api/v1/models.py:62`
- 详情：`backend/app/api/v1/models.py:88`
- 更新：`backend/app/api/v1/models.py:99`
- 启停：`backend/app/api/v1/models.py:119`
- 渠道概览：`backend/app/api/v1/models.py:139`

服务层能力：

- `backend/app/services/model_service.py:15` `list_model_hub_models`
- `backend/app/services/model_service.py:35` `create_model_hub_model`
- `backend/app/services/model_service.py:69` `update_model_hub_model`
- `backend/app/services/model_service.py:87` `set_model_hub_status`
- `backend/app/services/model_service.py:96` `list_model_channels`

当前创建模型时，如果传 `default_channel`，后端不会自己写 `api_key_enc`，而是调用 MaaS admin：

- 证据：`backend/app/services/model_service.py:47` 注释说明 “MaaS service owns channel secret encryption”
- 证据：`backend/app/services/model_service.py:128` `create_maas_channel`
- 证据：`backend/app/services/model_service.py:143` POST `${MAAS_BASE_URL}/admin/channels`

结论：后端业务层已经走通“创建模型 + 通过 MaaS 创建加密渠道”的最小路径。

### 1.3 MaaS 模型与渠道能力

MaaS admin API：

- `maas/app/api/admin.py:12` `GET /admin/channels`
- `maas/app/api/admin.py:16` `POST /admin/channels`
- `maas/app/api/admin.py:20` `GET /admin/channels/{channel_id}`
- `maas/app/api/admin.py:27` `PATCH /admin/channels/{channel_id}`
- `maas/app/api/admin.py:38` `DELETE /admin/channels/{channel_id}`
- `maas/app/api/admin.py:43` `POST /admin/channels/{channel_id}/health`

渠道创建 schema：

- `maas/app/schemas.py:7` `ChannelCreate`
- 包含 `model/model_type/provider/tenant_id/base_url/api_key/weight/rpm_limit/status`

MaaS 加密能力：

- `maas/app/services.py:37` `create_channel`
- `maas/app/services.py:41` 写入 `api_key_enc=encrypt_secret(payload.api_key)`
- `maas/app/services.py:89` 更新渠道时同样把 `api_key` 转为 `api_key_enc`
- `maas/app/core/crypto.py:14` `encrypt_secret`
- `maas/app/services.py:179` 调用外部模型前 `decrypt_secret(channel["api_key_enc"])`

MaaS OpenAI 兼容调用：

- `maas/app/api/openai.py:31` `GET /v1/models`
- `maas/app/api/openai.py:37` `POST /v1/chat/completions`
- `maas/app/api/openai.py:85` `POST /v1/embeddings`
- `maas/app/services.py:176` `proxy_openai`
- `maas/app/services.py:187` 请求外部 provider 时用 `Authorization: Bearer <api_key>`

当前健康检查不足：

- `maas/app/api/admin.py:43` `/admin/channels/{channel_id}/health`
- 当前逻辑只对 `mock://` 返回 `ok`，其他返回 `unknown`，没有真实发 chat/embedding 请求。

### 1.4 前端模型纳管页面

现有模型页面：

- 路由：`frontend/src/router/index.ts:13` `/model-hub`
- 侧边栏入口：`frontend/src/layouts/MainLayout.vue:28` “模型纳管”
- 页面：`frontend/src/views/ModelHubView.vue`

现有页面能力：

- `frontend/src/views/ModelHubView.vue:70` 加载 `/model-hub/models`
- `frontend/src/views/ModelHubView.vue:76` 手动创建模型
- `frontend/src/views/ModelHubView.vue:87` 创建时可带 `default_channel`
- `frontend/src/views/ModelHubView.vue:140` 启停模型
- `frontend/src/views/ModelHubView.vue:153` 查看渠道
- `frontend/src/views/ModelHubView.vue:262` API Key 输入框是 `password`

当前前端缺口：

- 没有模型目录/模型广场卡片。
- 没有从预置目录“一键接入”。
- 没有连接测试。
- 新建模型仍要求用户手动填 provider/name/base_url。

## 2. 产品设想对照 Gap

| 能力 | 现在有没有 | 现状证据 | 差距 | 本批次要补 |
|---|---|---|---|---|
| 运行态模型 | 有 | `backend/app/models/entities.py:205` `Model` | 已满足 | 复用，不重建 |
| 调用渠道 | 有 | `backend/app/models/entities.py:224` `ModelChannel` | 已满足 | 复用，不重建 |
| API Key 加密保存 | 有 | `maas/app/services.py:41` `encrypt_secret(payload.api_key)` | 已满足 | 一键接入继续走 MaaS admin |
| 手动创建模型+渠道 | 有 | `backend/app/services/model_service.py:35`、`frontend/src/views/ModelHubView.vue:76` | 需要用户手填过多信息 | 保留手动入口 |
| model_catalog 目录表 | 无 | 代码中无 `model_catalog` | 缺公共模型资料和预置接入配置 | 新增轻量目录表 |
| 模型广场/目录卡片 | 无 | `ModelHubView.vue` 只有表格 | 缺“选模型”入口 | 并入模型中心页面 |
| 一键接入 | 无 | 只有 `POST /model-hub/models` 手动创建 | 缺“从目录复制配置 + 用户填 key” | 新增目录接入接口 |
| 连接测试 | 弱 | `maas/app/api/admin.py:43` 只 mock ok/unknown | 非 mock 不做真实请求 | 新增真实最小 chat/embedding 测试 |
| 非 OpenAI 兼容适配 | 部分硬编码 | `maas/app/services.py:182` deepseek 特例 | 不具备通用适配器 | 第一版只做 OpenAI 兼容 |
| 模型体验页 | 无 | 无 dedicated playground | 超出本批次 | 后续 |
| 用量监控 | 有底层记录，无模型中心页 | `maas/app/services.py:222` `record_usage` | 缺模型维度看板 | 后续 |

## 3. 关键设计结论

### 3.1 model_catalog 与 models 的关系

建议：

- 新增 `model_catalog` 作为“公共模型资料 + 预置接入配置”表。
- `model_catalog` 不存 API Key，不直接参与运行。
- `models/model_channels` 仍是唯一运行态表。
- 第一版不在 `models` 上加 `catalog_id` 字段。
- 一键接入时，把目录来源写入 `models.provider_config`：

```json
{
  "catalog_code": "deepseek-chat",
  "catalog_provider": "deepseek",
  "protocol": "openai_compatible",
  "default_parameters": {"temperature": 0.7}
}
```

理由：

- 现有 `models.provider_config` 已是 JSONB，见 `backend/app/models/entities.py:213`。
- 不加 `catalog_id` 可以避免修改运行表结构，也避免 MaaS Table 同步改动。
- 目录只是产品资料，不应该成为模型运行的强依赖。
- 未来如果需要统计“由哪个目录接入”，可以先通过 `provider_config.catalog_code` 查询；到需要强关联时再补 `catalog_id`。

是否要加 `catalog_id`：

- 第一版不加。
- 后续如果要做目录版本升级、批量同步、目录项下架影响分析，再考虑加可空 `models.catalog_id`。

### 3.2 连接测试怎么实现

建议分两层：

1. 后端业务接口提供“测试某个渠道/测试某个目录接入配置”的 API。
2. 实际测试请求走 MaaS，因为 MaaS 拥有加密后的 API Key 和 OpenAI 兼容代理能力。

第一版实现路径：

- 对已经创建的渠道：
  - backend 找到 `model_channels`。
  - backend 调 MaaS 新增的真实 probe 接口，或直接调用 MaaS `/v1/chat/completions` / `/v1/embeddings`。
  - 更推荐新增 MaaS probe，因为 MaaS 可以直接用 channel id 解密并测试，不需要 backend 接触明文。
- 对“一键接入”流程：
  - 用户填 API Key。
  - 一键接入的连接测试必须遵守“先测试通过、再落库启用”的顺序；如果实现上必须先落库创建临时 channel，则测试失败时必须清理临时记录，或明确置为 disabled 且前端提示不可用，不能让错误 API Key 留下一批 `health=failed` 的僵尸渠道。
  - backend 调 MaaS `/admin/channels` 创建 channel，MaaS 加密保存。
  - backend 再调用连接测试。
  - 测试成功则 `model_channels.health=ok` 并启用；测试失败时按上面的清理/禁用原则处理。

测试请求策略：

- `llm`：发送最小 chat：

```json
{
  "model": "<runtime model name>",
  "messages": [{"role": "user", "content": "ping"}],
  "max_tokens": 8,
  "temperature": 0
}
```

- `embedding`：发送最小 embedding：

```json
{
  "model": "<runtime model name>",
  "input": "ping"
}
```

- `rerank`：本批次不做真实测试，先留 TODO。

当前证据：

- MaaS 已有真实代理：`maas/app/api/openai.py:37` chat，`maas/app/api/openai.py:85` embeddings。
- 当前 admin health 不足：`maas/app/api/admin.py:43` 只根据 `mock://` 判断。

### 3.3 一键接入如何复用 MaaS 加密写入

沿用模型纳管 Step2 已验证的路径：

- backend 接收目录项 id/code + 用户填的 API Key。
- backend 从 `model_catalog` 读取预置配置。
- backend 构造 `ModelHubCreate(default_channel=...)` 或新增专用 service。
- backend 调 MaaS `/admin/channels`。
- MaaS `create_channel` 创建/复用 `models`，并把 `api_key` 加密为 `api_key_enc`。
- backend 不落明文、不写 `api_key_enc`。

证据：

- `backend/app/services/model_service.py:47` 已明确采用 MaaS 加密路径。
- `backend/app/services/model_service.py:128` `create_maas_channel`
- `maas/app/services.py:37` `create_channel`
- `maas/app/services.py:41` `api_key_enc=encrypt_secret(payload.api_key)`

需要注意：

- MaaS `ensure_model` 只按 `models.name` 查找，见 `maas/app/services.py:19`。
- 因此目录中的 `model_code` 应作为 `models.name` 的默认值，必须唯一。
- 如果用户重复接入同一个 `model_code`，第一版应返回 `model_name_exists` 或让用户改 runtime name，不自动覆盖已有渠道。

### 3.4 首批目录数据建议

第一版只放 OpenAI 兼容或当前 MaaS 已能代理的模型。非 OpenAI 兼容先不放进“一键接入”闭环。

| provider | model_code | display_name | type | default_base_url | protocol | OpenAI 兼容 | 备注 |
|---|---|---|---|---|---|---|---|
| deepseek | deepseek-chat | DeepSeek Chat | llm | `https://api.deepseek.com` | openai_compatible | 是 | MaaS 已有 deepseek chat 特例，把请求 model 改为 `deepseek-chat`，证据 `maas/app/services.py:182` |
| deepseek | deepseek-reasoner | DeepSeek Reasoner | llm | `https://api.deepseek.com` | openai_compatible | 是 | 可能需要后续确认 MaaS 是否应保留 model 名；第一版可作为目录项但测试需实际 key |
| openai | gpt-4o-mini | GPT-4o mini | llm | `https://api.openai.com` | openai_compatible | 是 | 通用 OpenAI 协议 |
| openai | text-embedding-3-small | text-embedding-3-small | embedding | `https://api.openai.com` | openai_compatible | 是 | 用于知识库 embedding |
| qwen | qwen-plus | 通义千问 Plus | llm | `https://dashscope.aliyuncs.com/compatible-mode` | openai_compatible | 是 | DashScope 兼容模式，真实路径需验证 |
| mock | mock-chat | Mock Chat | llm | `mock://local` | mock | 是（内部 mock） | 本地验收用，无真实外部 key |
| mock | mock-embedding | Mock Embedding | embedding | `mock://local` | mock | 是（内部 mock） | 本地验收用 |

说明：

- 首批目录 seed 可以包含 mock，方便无外网/无真实 key 时验证闭环。
- 真实商业模型目录项不存 API Key，只存 base_url/protocol/recommended_parameters/official_url/pricing/icon 等资料。
- 非 OpenAI 兼容 provider 先留目录占位或不开放一键接入；需要适配器后再进入闭环。

## 4. 建议表结构：model_catalog

建议字段：

```text
id uuid primary key
provider text not null
model_code text not null unique
display_name text not null
model_type text not null -- llm/embedding/rerank
description text
context_window int
supports_streaming bool default false
supports_tools bool default false
supports_vision bool default false
default_base_url text not null
protocol text not null -- openai_compatible/mock/custom
recommended_parameters jsonb default '{}'
official_url text
pricing jsonb default '{}'
icon text
sort_order int default 100
is_active bool default true
created_at timestamptz default now()
updated_at timestamptz default now()
```

不包含：

- API Key
- `api_key_enc`
- 租户字段
- 运行状态字段

原因：

- 目录是公共资料，不是租户私有运行配置。
- 租户私有配置应该落到 `models/model_channels`。

## 5. 分步施工计划

### Step 1：model_catalog 表 + 迁移 + 首批 seed

目标：

- 新增目录表。
- 同步 ORM。
- seed 首批目录数据。
- 不改运行态模型逻辑。

预计改动文件：

- `backend/alembic/versions/<new>_model_catalog.py`
- `backend/app/models/entities.py`
- `backend/app/models/__init__.py`
- `backend/app/services/model_catalog_seed.py` 或放入现有 seed service
- 可能新增 `backend/app/scripts/seed_model_catalog.py`
- `docs/migration/12-step1-model-catalog-verify.md`

验证方式：

```bash
docker compose up -d --build backend postgres
docker compose exec backend alembic upgrade head
docker compose exec postgres psql -U app -d eap -c '\d model_catalog'
docker compose exec postgres psql -U app -d eap -c 'select provider, model_code, model_type, protocol, default_base_url from model_catalog order by provider, model_code;'
```

验收：

- 表存在。
- 首批目录数据存在。
- `models/model_channels` 不受影响。

### Step 2：目录列表/详情接口 + 前端模型中心目录卡片

目标：

- 后端提供目录列表和详情。
- 前端在模型中心并入“模型目录/模型广场”卡片，不新增单独菜单。

预计改动文件：

- `backend/app/schemas/model_catalog.py`
- `backend/app/services/model_catalog_service.py`
- `backend/app/api/v1/model_catalog.py` 或合并进 `api/v1/models.py`
- `backend/app/main.py`
- `frontend/src/api/types.ts`
- `frontend/src/views/ModelHubView.vue`
- `docs/migration/13-step2-model-catalog-api-ui-verify.md`

接口建议：

```text
GET /api/v1/model-center/catalog
GET /api/v1/model-center/catalog/{catalog_id}
```

验证方式：

```bash
docker compose up -d --build backend frontend

ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8001/api/v1/model-center/catalog \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

浏览器验证：

- 打开 `http://localhost:18080/model-hub`
- 看到模型目录卡片。
- 卡片展示 provider/display_name/type/context/protocol/base_url 等信息。

### Step 3：一键接入 + 连接测试接口

目标：

- 从目录项创建 `models`。
- 通过 MaaS 创建 `model_channels`，用户只填 API Key。
- 后端和前端都不保存 API Key 明文。
- 新增连接测试接口。

预计改动文件：

- `backend/app/schemas/model_catalog.py`
- `backend/app/services/model_center_service.py` 或扩展 `model_service.py`
- `backend/app/api/v1/model_center.py`
- `maas/app/api/admin.py`
- `maas/app/services.py`
- `maas/app/schemas.py`
- `docs/migration/14-step3-one-click-connect-verify.md`

接口建议：

```text
POST /api/v1/model-center/catalog/{catalog_id}/connect
POST /api/v1/model-center/models/{model_id}/test
POST /api/v1/model-center/channels/{channel_id}/test
```

`connect` 请求：

```json
{
  "runtime_name": "deepseek-chat",
  "api_key": "sk-...",
  "base_url": null,
  "weight": 1,
  "test_after_create": true
}
```

实现逻辑：

1. backend 读目录项。
2. backend 创建 `ModelHubCreate`。
3. backend 调 MaaS `/admin/channels`，MaaS 加密 API Key。
4. backend 调连接测试。
5. 返回 model/channel/health。

连接测试第一版：

- `mock://` 直接走 mock 并返回 ok。
- `llm` 调 MaaS chat 最小请求。
- `embedding` 调 MaaS embeddings 最小请求。
- `rerank` 返回 `not_supported`。

验证方式：

```bash
docker compose up -d --build backend maas postgres redis

curl -s -X POST http://localhost:8001/api/v1/model-center/catalog/<CATALOG_ID>/connect \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"runtime_name":"mock-chat-from-catalog","api_key":"mock-key","test_after_create":true}' \
  | python3 -m json.tool

curl -s http://localhost:8001/api/v1/model-hub/models?display_name=mock \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

验收：

- `models` 出现新逻辑模型。
- `model_channels` 出现渠道。
- `api_key_enc` 非明文。
- 测试结果 `health=ok`。
- 老 `/api/v1/models` 能看到新模型，智能体创建页可选。

### Step 4：前端接入流程串联

目标：

- 用户在模型中心点目录卡片。
- 弹出接入表单：显示预置 base_url/protocol/runtime_name，只填 API Key。
- 点击“测试连接”。
- 测试通过后启用模型。
- 智能体创建页可选该模型。

预计改动文件：

- `frontend/src/views/ModelHubView.vue`
- `frontend/src/api/types.ts`
- 可能拆组件：`frontend/src/components/model-center/*`
- `docs/migration/15-step4-model-center-ui-flow-verify.md`

验证方式：

```bash
docker compose up -d --build backend frontend maas postgres redis
```

浏览器手动验证：

- 打开 `http://localhost:18080/model-hub`
- 选择 mock 或 OpenAI 兼容目录项。
- 填 API Key。
- 点击测试。
- 成功后列表出现模型。
- 打开智能体工厂，模型下拉可选该模型。

## 6. 本批次边界

本批次只做“模型接入闭环”：

- model_catalog 目录表
- 目录列表/详情
- 目录卡片
- 一键接入
- 连接测试
- 接入后模型可被智能体选择

明确放后续批次：

- 模型体验页 / playground
- 模型用量和成本监控
- 多渠道权重策略 UI
- Rerank 模型真实测试
- 多模态 / 视觉模型测试
- 非 OpenAI 兼容 provider 适配器
- 模型价格自动同步
- 模型版本更新提醒
- 供应商官方模型列表自动拉取
- 组织级配额、计费、限流治理

## 7. Step 0 结论

最省事、最稳的路线：

1. 新增 `model_catalog` 作为公共目录，不参与运行。
2. 不改 `models/model_channels` 的核心职责。
3. 第一版不加 `models.catalog_id`，用 `provider_config.catalog_code` 记录来源。
4. 一键接入继续走 MaaS `/admin/channels`，复用加密写入。
5. 连接测试放在 MaaS 能力边界内，backend 只编排。
6. 首批只做 OpenAI 兼容和 mock，非兼容模型留适配器 TODO。
