# 06 知识库文档管理前端验证

本步只补齐前端文档管理 UI，不改后端接口。

## 接口契约确认

- 文档上传：`POST /api/v1/kbs/{kb_id}/documents`，`multipart/form-data`，字段名 `file`
- 文档列表：`GET /api/v1/kbs/{kb_id}/documents`
- 文档字段：`id / tenant_id / kb_id / name / source_uri / mime / size / parse_status / meta / created_at`
- 解析状态：`pending / parsing / done / failed`
- 支持文件：`.txt / .md / .pdf / .docx`，以及其它 `text/*`

## 构建与启动

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
npm --prefix frontend run build
docker compose up -d --build frontend
```

如果后端容器未运行：

```bash
docker compose up -d backend maas sandbox postgres redis minio
```

## 浏览器验证

1. ⚠️ 打开 `http://localhost:18080/kbs` 并强制刷新。
2. ⚠️ 创建一个新知识库。
   - 期望：提示“知识库已创建。下一步：上传文档开始构建知识库。”
   - 期望：自动打开该知识库的“文档管理”抽屉。
3. ⚠️ 上传一份 `.txt` 文档。
   - 期望：文档列表出现该文件。
   - 期望：状态从“待处理/解析中”变为“完成”。
   - 期望：状态到达“完成”或“失败”后停止轮询。可在 F12 Network 中确认不再持续请求 `/documents`。
4. ⚠️ 回到命中测试，选择该知识库检索文档中的关键词。
   - 期望：能看到片段卡片，包含文档名、分数和片段正文。
5. ⚠️ 上传一份 `.pdf` 文档，重复检查状态流转和命中测试。
6. ⚠️ 新建一个空知识库，打开文档面板。
   - 期望：空状态显示“还没有文档，上传 txt、pdf、md 或 docx 文档开始构建知识库。”
7. ⚠️ 对无完成文档的知识库执行命中测试。
   - 期望：页面提示“该知识库还没有解析完成的文档，检索将无结果。”

## 回归项

- 创建知识库仍正常。
- 知识库列表刷新仍正常。
- 原命中测试仍正常。
- 页面无控制台报错。
