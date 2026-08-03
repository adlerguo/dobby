# M1 知识入库质量提升验收记录

## 范围

本记录覆盖 M1 知识入库质量提升：批量文件导入、噪声文本剔除、重复内容检测、规则切片、基础元信息标注，以及知识库页面展示、检索结果 source 字段、文档和切片 meta 兼容性。

不包含页码级定位、检索重排序、知识版本管理、意图识别、上下文压缩、fallback、正误反馈、错误归档、安全评测、发布版本或回滚。

## 已实现能力

- 批量文件导入：`POST /kbs/{kb_id}/documents/batch` 支持多文件上传，单文件失败不影响其他文件；批次 ID 写入 `documents.meta.batch_id`。
- 批次状态聚合：`GET /kbs/{kb_id}/document-batches/{batch_id}` 基于 `documents.meta.batch_id` 聚合成功、失败和处理中数量。
- 噪声文本剔除：入库切片前执行清洗，记录清洗前后字符数、行数、移除行数和 `cleaning_version`。
- 重复内容检测：上传时记录文件 SHA-256；解析后记录文本 fingerprint；重复文档和重复文本只提示，不阻断入库；同文档内重复 chunk 标记 `duplicate_in_document`，不删除。
- 规则切片：支持 `simple`、`paragraph`、`markdown_heading`、`numbered_section`，结构识别失败时回退到 simple。
- 基础元信息标注：文档上传时默认写入 `documents.meta.source`；文档元信息可编辑；新入库 chunk 继承 source 字段；检索结果和 citation 返回 source 字段。
- 前端知识库页面：支持多文件上传、批次结果展示、质量列、切片结构信息、文档元信息编辑和检索 source 展示。

## 接口清单

- `POST /kbs/{kb_id}/documents/batch`
- `GET /kbs/{kb_id}/document-batches/{batch_id}`
- `PATCH /documents/{document_id}/meta`
- 既有 `POST /kbs/{kb_id}/documents` 单文件上传保持可用。
- 既有 `GET /kbs/{kb_id}/documents`、`GET /documents/{document_id}/chunks`、`POST /kbs/{kb_id}/retrieve` 保持可用，并扩展返回字段。

## 数据结构

文档级元数据复用 `documents.meta`：

- `batch_id`
- `file_sha256`
- `text_fingerprint`
- `duplicate`
- `warnings`
- `source`
- `ingest_task`

`ingest_task` 当前记录：

- `status`
- `raw_chars`
- `cleaned_chars`
- `raw_lines`
- `cleaned_lines`
- `removed_lines`
- `removed_blank_lines`
- `removed_noise_lines`
- `cleaning_version`
- `text_fingerprint`
- `chunk_strategy`
- `chunk_method`
- `fallback_chunking`
- `chunk_count`
- `embedding_dim`

切片级元数据复用 `chunks.meta`：

- `content_hash`
- `cleaning_version`
- `duplicate_in_document`
- `chunk_strategy`
- `chunk_method`
- `heading_path`
- `title_path`
- `section_no`
- `section_title`
- `parent_seq`
- `split_index`
- `fallback_chunking`
- `requested_chunk_strategy`
- `source_name`
- `source_type`
- `tags`
- `version_label`
- `published_at`

## 验收用例

- 批量上传合法文件和非法文件，合法文件成功，非法文件失败，批次结果返回 `batch_id`、总数、成功数、失败数和明细。
- 成功上传文档同时拥有 `batch_id`、`file_sha256`、`duplicate`、`source`。
- 清洗后 `Document.meta.ingest_task` 同时保留清洗统计、文本 fingerprint、切片策略、切片数量和向量维度。
- Markdown 文档使用 `markdown_heading` 后，chunk meta 写入 `heading_path` 和 `title_path`。
- 编号文档使用 `numbered_section` 后，chunk meta 写入 `section_no` 和 `section_title`。
- 同内容不同名文档标记 `text_duplicate`，但不阻断入库。
- 同文档内重复 chunk 标记 `duplicate_in_document`，但不删除。
- 检索结果和 citation 返回 `source_name`、`source_type`、`tags`、`version_label`、`published_at`。
- 历史文档缺少 `source`、`duplicate`、`ingest_task` 时，后端 source 字段回退为空值，前端展示使用安全默认值。

## 验证命令

- `python -m compileall backend/app`
- `python -m py_compile backend/tests/test_kb_batch_upload.py backend/tests/test_rag_cleaning.py backend/tests/test_rag_dedupe.py backend/tests/test_rag_chunking.py backend/tests/test_rag_ingest_m1.py backend/tests/test_document_meta_api.py backend/tests/test_m1_kb_quality_flow.py`
- `git diff --check`
- `cd frontend && npm run build`

当前本机 Python 环境缺少 `pytest`，`cd backend && python -m pytest ...` 未能执行，错误为 `No module named pytest`。需要在完整后端测试环境补跑 pytest。

当前本机 Python 环境也缺少后端运行依赖 `fastapi`、`anyio`、`sqlalchemy`，因此新增 helper 测试只能完成 `py_compile`，不能直接导入执行。

## 已知限制

- 批量任务仍使用 FastAPI `BackgroundTasks`，不是持久队列；服务重启或进程异常时不具备可靠任务恢复能力。
- 当前未新增 `document_batches` 表，批次状态依赖 `documents.meta.batch_id` 聚合。
- 历史文档需要重建索引后才有新的 chunk meta source 字段。
- 重复检测只提示，不阻断上传；重复 chunk 只标记，不删除。
- M1 未实现页码级定位，`page_start/page_end` 仍属于后续能力。
- M1 未实现按标签、来源、有效期过滤检索；当前只返回 source 字段。
- 清洗效果指标如“超短切片比例下降 30%”需要真实样本文档集和完整 pytest/集成环境进一步量化。

## 后续建议

- 进入 M2 前补齐完整后端测试环境，并运行所有 M1 pytest。
- 用一组真实 txt、md、docx、pdf、带页眉页脚、目录和重复文档构建固定验收集。
- 决定批量任务是否需要从 `BackgroundTasks` 升级为持久队列或批次表。
- 在 M2 中再处理页码级定位、引用增强、检索过滤、知识版本管理和重排序。
