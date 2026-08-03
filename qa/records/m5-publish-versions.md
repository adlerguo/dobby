# M5 发布运营能力验收记录

## 范围

本次只覆盖发布版本快照、版本激活、回滚、发布前检查和公开 API 使用 active version 快照。

不包含审批流、灰度发布、多环境发布、API Key 体系重构、知识版本回滚、真实 rerank 模型或安全评测平台化门禁。

## 已实现能力

- 发布应用时自动生成 `published_app_versions` v1 快照，并写入 `published_apps.active_version_id`。
- 支持创建新的发布版本，快照包含 agent 基础配置、persona、model_id、kb_ids、tool_ids。
- 支持版本激活和回滚，本质是切换 `published_apps.active_version_id` 并将对应版本标记为 active。
- 支持发布前检查，当前阻断项为 agent 不可用、模型未配置或不可用；知识库状态、工具状态、open 高危问题、安全评测失败为 warning。
- 公开 `/public/apps/{app_id}/chat` 和 OpenAI 兼容接口默认使用 active version 的 runtime snapshot。
- 发布中心页面展示当前版本、发布前检查、版本历史、创建新版本、设为当前和回滚。

## 接口清单

- `POST /api/v1/published-apps/{app_id}/precheck`
- `POST /api/v1/published-apps/{app_id}/versions`
- `GET /api/v1/published-apps/{app_id}/versions`
- `POST /api/v1/published-apps/{app_id}/versions/{version_id}/activate`
- `POST /api/v1/published-apps/{app_id}/rollback`

既有接口保留：

- `POST /api/v1/published-apps`
- `GET /api/v1/published-apps`
- `GET /api/v1/published-apps/{app_id}`
- `POST /api/v1/published-apps/{app_id}/unpublish`
- `POST /api/v1/published-apps/{app_id}/keys`
- `GET /api/v1/published-apps/{app_id}/keys`
- `POST /api/v1/published-apps/{app_id}/keys/{key_id}/status`

## 数据结构

新增迁移：

- `backend/alembic/versions/202607310003_published_app_versions.py`

新增字段：

- `published_apps.active_version_id`

新增表：

- `published_app_versions`

核心字段：

- `tenant_id`
- `app_id`
- `agent_id`
- `version_no`
- `status`
- `title`
- `release_note`
- `snapshot`
- `precheck_result`
- `created_by`
- `activated_at`

历史发布应用迁移时会补一个 v1 快照，但迁移阶段无法可靠还原 agent-kb、agent-tool 当前绑定，历史 v1 的 `kb_ids` 和 `tool_ids` 可能为空，需要后续重新创建版本补齐。

## 验收用例

- 发布应用后应存在 active version，应用列表返回 `active_version_id` 和 `active_version_no`。
- 创建新版本后可选择是否立即激活。
- 激活旧版本或调用 rollback 后，公开 API 使用被激活版本的 snapshot。
- agent 草稿后续修改不应影响已发布版本的 persona、config、model_id、kb_ids、tool_ids。
- 发布前检查能返回 passed、warning 或 blocked，并在 blocked 时默认阻止创建版本；前端可勾选强制发布。
- 原有 API Key 生成、停用、启用、公开调用仍保持兼容。

## 验证命令

已执行：

- `python -m compileall backend/app`
- `python -m py_compile backend/tests/test_publish_versions.py backend/tests/test_public_agents_stream.py backend/tests/test_openai_compat.py backend/tests/test_agent_path_smoke.py backend/tests/test_audit_permissions.py backend/tests/test_dashboard_usage_aggregation.py`
- `python -m py_compile backend/alembic/versions/202607310003_published_app_versions.py`
- `git diff --check`
- `cd frontend && npm run build`

未通过本地执行：

- `cd backend && python -m pytest tests/test_publish_versions.py`

失败原因：当前 Python 环境缺少 `pytest`，输出为 `No module named pytest`。需要在完整后端依赖环境补跑。

## 已知限制

- 批量任务仍使用 FastAPI BackgroundTasks，不是持久队列。
- 历史发布应用迁移生成的 v1 快照只能保证基础字段，不保证还原完整 KB/Tool 绑定。
- 发布前检查目前是结构化状态检查，基础评测和安全评测门禁只通过 open incident 状态间接判断。
- 强制发布只绕过 blocked precheck，不提供审批和二次确认工作流。
- 公开 API 使用 active version 快照；如果历史应用没有 active version，则回退到原实时 agent 逻辑以兼容旧数据。
- 管理端智能体调试仍使用实时配置，不使用发布快照。
- 真实 rerank 模型未实现，仍按现有规则/回退能力处理。

## 后续建议

- 在完整测试环境补跑发布版本的 API 集成测试和公开 API 行为测试。
- 为发布前检查接入正式 eval run 和 security eval run 结果，而不只依赖 open incident。
- 为历史发布应用提供“一键重建当前版本快照”操作。
- 进入更复杂发布治理前，再设计审批流、灰度和多环境模型。
