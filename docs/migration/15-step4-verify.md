# Step 4 验证：模型中心前端一键接入流程

本步把 Step 3 已验证的后端接口串到前端。需要重建 frontend；如果你还没有用最新 backend 镜像，也一起重建 backend。

## 0. 启动与登录

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend maas postgres redis minio sandbox
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed_model_catalog
```

登录拿 token：

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

## 1. 确认重测接口路由

Step 3 的源码已经注册到 `backend/app/main.py`，正确路径是：

```text
POST /api/v1/model-center/channels/{channel_id}/test
```

如果这里返回 404，优先检查是否重新 `--build backend`。

可用 OpenAPI 确认路由存在：

```bash
curl -s http://localhost:8001/api/v1/openapi.json \
  | python3 -c 'import sys,json; data=json.load(sys.stdin); print("/api/v1/model-center/channels/{channel_id}/test" in data["paths"])'
```

期望输出：`True`。

## 2. ⚠️ 浏览器：mock-chat 一键接入成功

1. 打开 `http://localhost:18080/model-hub`，必要时按 `Cmd+Shift+R` 强制刷新。
2. 在“模型广场”找到 `mock-chat`，点击“接入使用”。
3. 弹窗里确认预置信息存在：供应商、目录编码、协议、默认地址。
4. 填写：
   - 内部模型名：`ui-mock-` 加当前时间，例如 `ui-mock-0712`
   - API Key：`mock-key`
   - 覆盖地址：保持 `mock://local`
   - 权重：`1`
5. 点击“测试并接入”。

期望：

- 提示“模型已接入”。
- 弹窗关闭。
- 下方“已接入模型”列表出现刚才的内部模型名。
- 密钥不会在页面任何列表、详情、渠道抽屉中回显。

## 3. ⚠️ 浏览器：商业模型错误 key 失败但不关弹窗

1. 在“模型广场”找到 `gpt-4o-mini`，点击“接入使用”。
2. 内部模型名填一个不存在的新名字，例如 `ui-bad-key-0712`。
3. API Key 填明显错误值：`sk-obviously-wrong`。
4. 点击“测试并接入”。

期望：

- 弹窗内显示“连接测试失败，请检查 API Key 和地址”。
- 弹窗不关闭。
- 下方“已接入模型”列表不会出现 `ui-bad-key-0712`。

可选数据库确认不留脏数据：

```bash
BAD_RUNTIME="ui-bad-key-0712"
docker compose exec postgres psql -U app -d eap \
  -c "select count(*) from models where name = '$BAD_RUNTIME';"
docker compose exec postgres psql -U app -d eap \
  -c "select count(*) from model_channels c join models m on m.id = c.model_id where m.name = '$BAD_RUNTIME';"
```

期望两个结果都是 `0`。

## 4. ⚠️ 浏览器：渠道重新测试

1. 在下方“已接入模型”列表找到一个已接入模型。
2. 点击“渠道”。
3. 在渠道抽屉点击“重新测试”。

期望：

- mock 渠道提示“连接测试通过”。
- `health` 显示为 `ok`。

也可以用 curl 验证：

```bash
CHANNEL_ID="<替换为渠道抽屉里对应的channel id，或用Step3文档生成的CHANNEL_ID>"

curl -s -X POST "http://localhost:8001/api/v1/model-center/channels/$CHANNEL_ID/test" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：`test_result.ok=true`，`channel.health=ok`。

## 5. ⚠️ 浏览器：智能体可选到新接入模型

1. 打开“智能体工厂”。
2. 新建或编辑智能体。
3. 打开模型下拉。

期望：能看到 Step 2 接入成功的内部模型名，例如 `ui-mock-0712`。这表示“模型广场接入 → 模型纳管 → 智能体可选”的闭环打通。

## 6. curl 回归

目录接口：

```bash
curl -s http://localhost:8001/api/v1/model-center/catalog \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

模型纳管：

```bash
curl -s http://localhost:8001/api/v1/model-hub/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

老模型下拉：

```bash
curl -s http://localhost:8001/api/v1/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

手动创建回归：

```bash
MANUAL_MODEL="manual-regression-$(date +%s)"
curl -s -X POST http://localhost:8001/api/v1/model-hub/models \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"$MANUAL_MODEL\",\"provider\":\"mock\",\"type\":\"llm\",\"display_name\":\"手动回归模型\",\"default_channel\":{\"base_url\":\"mock://local\",\"api_key\":\"mock-key\",\"weight\":1,\"status\":\"active\"}}" \
  | python3 -m json.tool
```

RAG 链路回归：复跑之前已验证过的 `/kbs/{id}/retrieve`、`/agents/{id}/context`、`/chat` 三个命令即可。本步只改模型中心前端和请求封装，不改 RAG 逻辑。
