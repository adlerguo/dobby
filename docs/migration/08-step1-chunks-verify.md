# 08 Step 1 切片可视化验证

本步目标：只读查看文档切片，不改切分、检索、入库逻辑。

## 1. 构建与启动

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend
```

如依赖服务未启动：

```bash
docker compose up -d maas sandbox postgres redis minio
```

## 2. 浏览器验证

1. ⚠️ 打开 `http://localhost:18080/kbs` 并强制刷新。
2. ⚠️ 找到包含 `销售一纸禅-联通信创云.docx` 的知识库，点击“文档”。
3. ⚠️ 在文档列表中点击该文档的“查看切片”。
4. 期望：
   - 切片摘要显示 `共 3 片`。
   - 平均长度约 `739` 字符。
   - 切分方法为 `paragraph_window`。
   - 三片长度约为 `779 / 724 / 715`。
   - 每片均显示“已有向量”。
   - 默认展示前 200 字，点击“展开全文”可查看完整内容。

## 3. curl 验证接口字段

登录并取目标文档：

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

DOC_ID=$(docker compose exec -T postgres psql -U app -d eap -tA -c \
  "select id from documents where name='销售一纸禅-联通信创云.docx' order by created_at desc limit 1;")
```

请求切片接口：

```bash
curl -s http://localhost:8001/api/v1/documents/$DOC_ID/chunks \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望每条包含：

- `id`
- `seq`
- `content`
- `content_length`
- `tokens`
- `meta`
- `has_embedding`
- `created_at`

快速核对数量和长度：

```bash
curl -s http://localhost:8001/api/v1/documents/$DOC_ID/chunks \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print(len(data), [x["content_length"] for x in data], [x["has_embedding"] for x in data], data[0]["meta"])'
```

期望类似：

```text
3 [779, 724, 715] [True, True, True] {'chunk_method': 'paragraph_window'}
```

## 4. 权限验证

未登录访问：

```bash
curl -i http://localhost:8001/api/v1/documents/$DOC_ID/chunks
```

期望：`401 Unauthorized`。

不存在或不可访问文档：

```bash
curl -i http://localhost:8001/api/v1/documents/00000000-0000-0000-0000-000000000000/chunks \
  -H "Authorization: Bearer $ACCESS"
```

期望：`404`，且不返回其它租户或内部信息。

如果本地有其它租户文档，可替换成其它租户的 `document_id` 再测，期望同样是 `404`。

## 5. 回归

1. ⚠️ 上传文档仍正常。
2. ⚠️ 文档状态轮询仍正常。
3. ⚠️ 命中测试仍正常。
4. 页面无控制台报错。
