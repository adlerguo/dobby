# Step 3 文档上传 / 解析 / 切片 / Embedding / 入库测试

执行时间：2026-07-14 12:36:33 +0800
MaaS PRODUCTION_MODE：`false`

## 第 1 组：正常主链路 1536

| 文件 | parse_status | chunk_count | 落表 | 维度 | 结论 |
|---|---|---:|---|---:|---:|
| normal.txt | done | 1 | chunks | 1536 | PASS |
| normal.md | done | 1 | chunks | 1536 | PASS |
| normal.docx | done | 1 | chunks | 1536 | PASS |
| normal.pdf | done | 1 | chunks | 1536 | PASS |

## 第 2 组：切片参数 / 空文件

- 小 chunk KB：`{"status": {"parse_status": "done", "meta": "{\"ingest_task\": {\"status\": \"done\", \"chunk_count\": 607, \"embedding_dim\": 1536}, \"object_name\": \"tenants/87ae1a50-9249-4e...`
- 大 chunk KB：`{"status": {"parse_status": "done", "meta": "{\"ingest_task\": {\"status\": \"done\", \"chunk_count\": 243, \"embedding_dim\": 1536}, \"object_name\": \"tenants/87ae1a50-9249-4e...`
- 空文件：`{"upload": 201, "status": {"parse_status": "failed", "meta": "{\"ingest_task\": {\"error\": \"document_has_no_text\", \"status\": \"failed\"}, \"object_name\": \"tenants/87ae1a5...`
- 结论：PASS

## 第 3 组：异常与鲁棒

- 损坏 PDF：`{"upload": 201, "status": {"parse_status": "failed", "meta": "{\"ingest_task\": {\"error\": \"Stream has ended unexpectedly\", \"status\": \"failed\"}, \"object_name\": \"tenant...`
- 超长文档：`{"upload": 201, "status": {"parse_status": "done", "meta": "{\"ingest_task\": {\"status\": \"done\", \"chunk_count\": 304, \"embedding_dim\": 1536}, \"object_name\": \"tenants/8...`
- 重复 ingest：`{"response": {"status": 200, "body": {"kb_id": "96ba1501-e85a-4b68-9ae6-eba71d3203e1", "document_count": 1, "status": "queued"}}, "before": {"chunks": {"count": "304", "dim": "1...`
- 删除 MinIO 源后 force reindex：`{"delete_source": {"code": 0, "stdout": "deleted\n", "stderr": ""}, "reindex": {"response": {"status": 200, "body": {"kb_id": "96ba1501-e85a-4b68-9ae6-eba71d3203e1", "document_c...`

## 第 4 组：维度路由

- `chunk_model_for_dim` 单元脚本：code=0, stdout=`PASS`
- 非法维度构造：`{"channel": {"status": 201, "body": {"id": "d9b68ed7-285f-43c0-ad76-e48ff4628413", "tenant_id": "87ae1a50-9249-4ee0-a69d-bb1600914927", "model_id": "f19a13c3-a1fa-4acb-85d9-97e8...`
- 1024/3072 端到端：待真实 embedding key 补测。

## 第 5 组：Embedding 模型锁定

| 用例 | 状态码/状态 | detail | 结论 |
|---|---:|---|---:|
| 有文档 KB PATCH embedding_model | 409 | `kb_embedding_model_locked_has_documents` | PASS |
| 空 KB PATCH embedding_model | 200 | `None` | PASS |

## Demo 已验 / 待真实 key 补测

- Demo 已验：txt/md/docx/pdf 解析、1536 mock embedding 入 `chunks`、切片参数、空文件、损坏 PDF、超长文本、force reindex、MinIO 源缺失兜底、模型锁定逻辑、chunk_model_for_dim。
- 待真实 key 补测：1024/3072 embedding 端到端写入 `chunks_1024` / `chunks_3072` 并检索命中；真实 provider 非法维度返回 `unsupported_embedding_dim` 的 API 构造路径。

## 缺陷记录

- 未发现本步阻断性缺陷。

## 结论

- 文档处理与入库链路是否可靠：是，demo 主链路通过。
- 是否可以进入 Step 4：可以。
