# M2 引用与检索增强验收记录

## 范围

本记录覆盖 M2 引用与检索增强：页码级定位、检索重排序、知识版本管理，以及前端知识库页面和对话引用展示的联调检查。

不包含意图识别、上下文压缩、fallback、正误反馈、错误归档、安全评测、发布版本/回滚，也不改变现有检索召回方式和排序默认行为。

## 已实现能力

- 页码级定位：解析层输出 `ParsedBlock`，PDF block 保留页码，DOCX/MD/TXT 至少保留段落或块序号；切片聚合后写入 `chunks.meta.page_start/page_end/paragraph_start/paragraph_end/block_start/block_end`。
- Citation 扩展：`RetrievedChunkOut` 和 `CitationOut` 返回 source、页码、段落、块定位、rerank 字段；旧 chunk 缺少新 meta 字段时返回空值，不抛错。
- 检索重排序：支持 `rerank_mode=off/rule/model`；默认 `off` 保持既有顺序；`rule` 基于 hybrid 分数、来源、结构、页码和重复标记做轻量重排；`model` 当前可配置但降级到 rule，并返回 fallback 标记。
- 版本管理：在 `documents` 表扩展 `logical_doc_id`、`version_no`、`version_status`、`version_parent_id`、`activated_at`；支持上传新版本、版本列表、解析完成后手动激活。
- 版本隔离：vector 检索和 keyword 检索均只命中 `version_status='active'` 的文档。
- 前端联调：知识库页面展示版本入口、新版本上传、版本列表、手动激活、页码/source/结构信息、rerank 配置和检索结果字段；对话工作台 citation 展示页码和 rerank 信息。

## 接口清单

- `POST /documents/{document_id}/versions`
- `GET /documents/{document_id}/versions`
- `POST /documents/{document_id}/versions/{version_id}/activate`
- `POST /kbs/{kb_id}/retrieve`：扩展 `rerank_mode` 入参和 source/location/rerank 出参。
- Chat/Public Chat/Agent Run 入参扩展 `rerank_mode`，运行 trace 记录 rerank 汇总。

## 数据结构

数据库迁移：

- `backend/alembic/versions/202607310001_document_versions.py`

`documents` 新增或回填字段：

- `logical_doc_id`
- `version_no`
- `version_status`
- `version_parent_id`
- `activated_at`

索引和约束：

- 文档名唯一约束改为只约束 active 版本。
- 同一逻辑文档同一时间只允许一个 active 版本。
- 同一逻辑文档的 `version_no` 在知识库内唯一。

`documents.meta` 继续兼容 M1 字段，并新增轻量版本信息：

- `source.version_label`
- `version.version_no`
- `version.parent_document_id`
- `version.created_from`

`chunks.meta` 扩展定位字段：

- `page_start`
- `page_end`
- `paragraph_start`
- `paragraph_end`
- `block_start`
- `block_end`

检索返回扩展字段：

- `source_name/source_type/tags/version_label/published_at`
- `page_start/page_end/paragraph_start/paragraph_end/block_start/block_end`
- `rerank_mode/rerank_score/rerank_factors/rerank_fallback`

## 验收用例

- PDF 文档解析后 chunk meta 写入页码范围，citation 返回 `page_start/page_end`。
- MD/DOCX/TXT 文档没有页码时不报错，仍返回段落或块定位字段。
- 历史 chunk 缺少 page/source/rerank 相关 meta 时，Schema 和前端展示不报错。
- `rerank_mode=off` 保持原召回顺序和既有分数。
- `rerank_mode=rule` 返回 rerank 分数、因素和前后可观察差异。
- `rerank_mode=model` 在未配置真实模型服务时降级 rule，并返回 `rerank_fallback=true`。
- 上传新版本后文档先保持 inactive，不参与默认检索。
- 未解析完成的新版本不能激活；解析完成后可手动激活。
- 激活历史版本后旧 active 版本变为 inactive，默认检索只命中新 active 版本。
- 知识库设置保存 rerank/chunking 配置时，不覆盖 `config.cleaning` 等已有配置。

## 验证命令

- `python -m compileall backend/app`
- `python -m py_compile backend/alembic/versions/202607310001_document_versions.py`
- `python -m py_compile backend/tests/test_rag_parsers_blocks.py backend/tests/test_rag_chunk_locations.py backend/tests/test_rag_rerank.py backend/tests/test_rag_retrieve_rerank_hook.py backend/tests/test_document_versions.py backend/tests/test_rag_ingest_m1.py`
- `git diff --check`
- `cd frontend && npm run build`

当前本机 Python 环境缺少 `pytest`，`cd backend && python -m pytest ...` 未能执行，需要在完整后端测试环境补跑。

当前本机 Python 环境也缺少后端运行依赖 `fastapi`、`anyio`、`sqlalchemy`、`docx`、`pypdf`，因此 parser、retrieve、service 相关测试本次以 `py_compile` 和前端 build 为主。

## 已知限制

- 历史文档需要重建索引后才会拥有新的 chunk meta source 和 page/location 字段。
- `model` rerank 当前只是可配置降级路径，没有接入真实 MaaS rerank client。
- rule rerank 是轻量启发式，不代表固定测试集 top1 已量化提升；需要真实检索评测集补验。
- 文档版本管理采用 `documents` 扩展字段，不新增 `document_groups` 或 `document_versions` 表。
- 版本差异摘要目前仅预留在 `documents.meta.version`，未实现完整 diff 报告。
- 回滚采用“激活历史版本”的轻量实现，不包含发布版本回滚。
- 新版本上传仍使用现有上传与 FastAPI BackgroundTasks 解析链路，不是持久队列。
- 上线前必须执行 Alembic 迁移；未迁移数据库无法使用版本字段和新唯一约束。

## 后续建议

- 在完整依赖环境补跑 M1/M2 后端 pytest，并补一组真实 PDF 页码样本校验。
- 用固定检索集量化 off/rule/model 降级路径的 top1 命中率、重复片段比例和延迟增量。
- M3 开始前确认 `rerank_mode` 在智能体配置、请求参数和 trace 中的优先级是否满足产品预期。
- 如果版本运营复杂度继续上升，再评估是否拆出 `document_groups` 或独立版本表。
