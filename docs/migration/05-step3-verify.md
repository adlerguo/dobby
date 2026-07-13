# Step 3 Verify: Model Hub Frontend

本步骤验证 Vue3 前端新增的“模型纳管”页面。

注意：当前 `frontend/Dockerfile` 会把本地 `frontend/dist` 复制进 Nginx 镜像，所以修改前端源码后必须先 `npm run build`，再 `docker compose up -d --build frontend`。

## 0. 前置启动

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

docker compose up -d postgres redis minio maas sandbox backend
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed

cd frontend
npm run build

cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend frontend
```

健康检查：

```bash
curl -s http://localhost:8001/healthz
curl -s http://localhost:8100/healthz
curl -I http://localhost:18080
```

## 1. 进入模型纳管页面

浏览器打开：

```text
http://localhost:18080
```

如果未登录，使用：

```text
租户：default
用户名：admin
密码：Admin123!
```

期望：

- 左侧导航出现“模型纳管”。
- 点击后进入 `/model-hub`。
- 页面能看到模型列表，包含 `display_name`、`name`、`provider`、`type`、`is_active`、`import_source`、`created_at` 等列。
- 页面至少能看到已有模型，例如 `mock-chat`、`mock-embedding`、之前配置过的 `siyids测试模型` 等。

如果浏览器仍看不到菜单，先强制刷新：

```text
Cmd + Shift + R
```

## 2. 新建模型

在“模型纳管”页面点击“新建模型”，填写：

```text
模型名：ui-test-model
供应商：mock
类型：LLM
展示名：UI 测试模型
说明：前端模型纳管验证
默认渠道：创建
渠道地址：mock://local
密钥：mock-key
权重：1
```

点击“创建”。

期望：

- 弹窗关闭。
- 页面提示创建成功。
- 列表刷新后能看到 `ui-test-model`。
- 页面任何位置不显示 `mock-key`。

## 3. 编辑展示名

在 `ui-test-model` 行点击“编辑”，修改：

```text
展示名：UI 测试模型-已更新
说明：编辑验证通过
```

点击“保存”。

期望：

- 列表展示名更新为 `UI 测试模型-已更新`。
- 刷新浏览器后仍保持。

## 4. 停用/启用

在 `ui-test-model` 行点击“停用”。

期望：

- 状态变为“停用”。
- 刷新浏览器后仍为停用态。

再点击“启用”，确认状态恢复“启用”。

## 5. 重名错误友好提示

再次点击“新建模型”，填写同名：

```text
模型名：ui-test-model
供应商：mock
类型：LLM
默认渠道：暂不创建
```

点击“创建”。

期望：

- 前端显示“模型名已存在”。
- 页面不白屏。
- 不显示原始堆栈或未处理错误。

也可以用已存在的 `model-hub-test` 验证，如果你 Step 2 已创建过它。

## 6. 查看渠道不泄露密钥

在任意模型行点击“渠道”。

期望：

- 抽屉打开。
- 能看到 `base_url`、`status`、`health`、`weight`、`created_at`。
- 看不到 `api_key`、`api_key_enc`、`mock-key` 或任何 `sk-` 密钥。

## 7. 回归智能体创建页

进入：

```text
http://localhost:18080/agents
```

打开“创建向导”，查看模型下拉。

期望：

- 智能体创建页仍正常。
- 模型下拉仍可加载。
- 仍使用老接口 `/api/v1/models` 的兼容数据，不受模型纳管页面影响。
- 能看到刚创建的 `ui-test-model` 或其他已有模型。

## 8. 可选接口辅助检查

如果页面数据异常，可先用接口确认：

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s "http://localhost:8001/api/v1/model-hub/models?limit=100" \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

检查前端是否加载新构建：

```bash
curl -s http://localhost:18080/index.html
```

期望能看到新版 `index-*.js`，且浏览器开发者工具 Network 中有 `ModelHubView-*.js`。

