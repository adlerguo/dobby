# Step 0 环境记录

执行时间：2026-07-14 Asia/Shanghai

## 只读边界

- 本步只读取业务代码与配置。
- 新建/写入范围仅限 `qa/`：
  - `qa/README.md`
  - `qa/records/step0-env.md`
  - `qa/env/admin_token.txt`
  - `qa/env/admin_login_response.json`
  - `qa/env/admin_token_payload.json`
  - `qa/env/quickstart-step0.log`
  - `qa/env/mock_catalog.json`
  - `qa/env/maas_channels.json`
  - `qa/env/admin_me.json`
  - `qa/env/mock_chat_response.json`
  - `qa/env/mock_embedding_response.json`

## 读取源码结论

只读文件：

- `deploy/quickstart.sh`
- `docker-compose.yml`
- `backend/app/scripts/seed.py`
- `backend/app/scripts/seed_model_catalog.py`
- `backend/app/scripts/seed_examples.py`
- `backend/app/services/rbac_service.py`

默认管理员：

- `tenant_code`: `default`
- `username`: `admin`
- `password`: `Admin123!`
- 租户：`默认租户`
- 管理员显示名：`平台管理员`
- 管理员邮箱：`admin@example.local`
- 管理员角色：`super_admin`

默认角色与权限：

- `super_admin`: 14 个权限
- `tenant_admin`: 11 个权限
- `builder`: 3 个权限
- `member`: 1 个权限

demo 模式预期 seed：

- 模型目录 mock 项：
  - `mock-chat`, provider=`mock`, model_type=`llm`, protocol=`mock`, default_base_url=`mock://local`
  - `mock-embedding`, provider=`mock`, model_type=`embedding`, protocol=`mock`, default_base_url=`mock://local`
- 示例模型：
  - runtime model `mock-chat`
  - runtime model `mock-embedding`
- 示例知识库：
  - `示例知识库：合同审批`
  - 文档 `合同审批要点.txt`
  - embedding model `mock-embedding`
- 示例工具：
  - `12345问数`, builtin=`nl2data`, db_path=`demo_data/12345_workorders_demo.sqlite`, allowed_tables=`work_orders`
- 示例 Agent：
  - `示例知识问答 Agent`, type=`qa`
  - `示例智能问数 Agent`, type=`nl2data`

## 启动记录

执行命令：

```bash
PRODUCTION_MODE=false SEED_DEMO_MODE=true bash deploy/quickstart.sh
```

结果：

- quickstart 成功退出。
- 构建均使用缓存，镜像构建完成：
  - `6qiyeagent-backend:latest` image id `6d83ce79e4fb`
  - `6qiyeagent-maas:latest` image id `82017d9bf0fa`
  - `6qiyeagent-sandbox:latest` image id `73ba09c19f0d`
  - `6qiyeagent-frontend:latest` image id `41cd70cffbc6`
  - infra image: `pgvector/pgvector:pg15`, `redis:7-alpine`, `minio/minio:latest`
- MaaS 容器实际环境变量验证：
  - `PRODUCTION_MODE=false`

注意事项：

- 启动前目标端口已被同一 compose 项目的容器占用，未发现外部端口冲突，未修改 compose 端口。
- quickstart 日志中出现：

```text
SEED_DEMO_MODE=true，写入显式演示数据...
SEED_DEMO_MODE is not true; skip mock/demo example seed.
```

初步判断：宿主机命令行传入的 `SEED_DEMO_MODE=true` 被 quickstart shell 判断到了，但 `docker compose exec -T backend python -m app.scripts.seed_examples` 运行在 backend 容器内，容器环境没有拿到 `SEED_DEMO_MODE=true`，因此当前 quickstart 没有按预期执行示例 seed。未修正代码。

## 健康检查

curl 结果：

```text
GET http://localhost:8001/healthz
{"service":"backend","status":"ok","version":"0.1.0"}

GET http://localhost:8100/healthz
{"service":"maas","status":"ok","version":"0.1.0"}

GET http://localhost:8200/healthz
{"service":"sandbox","status":"ok","version":"0.1.0"}

HEAD http://localhost:18080
HTTP/1.1 200 OK
Server: nginx/1.27.5
Content-Type: text/html
```

`docker compose ps` 摘要：

```text
backend    Up, 8001->8001
frontend   Up, 18080->80
maas       Up, 8100->8100
minio      Up (healthy), 9000-9001->9000-9001
postgres   Up (healthy), 5432->5432
redis      Up (healthy), 6379->6379
sandbox    Up, 8200->8200
```

说明：compose 文件只给 `postgres`、`redis`、`minio` 配置了 Docker healthcheck；`backend`、`maas`、`sandbox`、`frontend` 通过 curl 可达性验证健康。

## Git 基线

```text
git HEAD = aeb7bd5e4a8e4d30783eb4648df4e93f85483728
```

## 管理员登录与 token

登录接口：

```text
POST http://localhost:8001/api/v1/auth/login
body: {"tenant_code":"default","username":"admin","password":"Admin123!"}
```

结果：

- 登录成功。
- access token 已保存到 `qa/env/admin_token.txt`。
- token payload 已保存到 `qa/env/admin_token_payload.json`。

access token payload 关键字段：

```json
{
  "roles": ["super_admin"],
  "typ": "access",
  "iat": 1784000327,
  "exp": 1784003927,
  "iat_iso_utc": "2026-07-14T03:38:47+00:00",
  "exp_iso_utc": "2026-07-14T04:38:47+00:00"
}
```

`GET /api/v1/auth/me` 结果摘要：

- username: `admin`
- display_name: `平台管理员`
- roles: `super_admin`
- permissions 包含 `maas:admin`、`kb:create`、`agent:publish`、`dashboard:view`、`audit:view` 等。

## Demo 渠道与链路验证

MaaS 渠道：

- 存在 active mock LLM 渠道：
  - `mock-chat`, provider=`mock`, model_type=`llm`, base_url=`mock://local`, status=`active`, health=`ok`
  - 另有多个历史 mock LLM 渠道处于 active
- 存在 active mock embedding 渠道：
  - `mock-embedding`, provider=`mock`, model_type=`embedding`, base_url=`mock://local`, status=`active`, health=`ok`

MaaS chat 验证：

```text
POST http://localhost:8100/v1/chat/completions
body: {"model":"mock-chat","messages":[{"role":"user","content":"ping"}]}
```

返回：

```json
{
  "model": "mock-chat",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "mock response: ping"
      },
      "finish_reason": "stop"
    }
  ]
}
```

MaaS embedding 验证：

```text
POST http://localhost:8100/v1/embeddings
body: {"model":"mock-embedding","input":"ping"}
```

返回摘要：

```text
model=mock-embedding, object=list, data_len=1, embedding_dim=1536
```

模型目录状态：

- `model_catalog` 中 `mock-chat` 与 `mock-embedding` 当前为 `is_active=false`。
- 这与 quickstart 中容器内未拿到 `SEED_DEMO_MODE=true` 的现象一致。
- 但 runtime `models` 表与 MaaS `model_channels` 中已有 active mock 模型/渠道，因此 demo 链路可以走通。

## 基线快照

默认租户/管理员：

```text
tenant_code=default
tenant_name=默认租户
username=admin
display_name=平台管理员
email=admin@example.local
status=active
```

默认租户角色：

```text
builder      构建者      3 permissions
member       普通成员    1 permissions
super_admin  平台管理员  14 permissions
tenant_admin 租户管理员  11 permissions
```

当前示例/历史数据清单：

- Agents:
  - `示例知识问答 Agent`, type=`qa`, status=`active`
  - `示例智能问数 Agent`, type=`nl2data`, status=`active`
  - 另有既有测试 Agent：`step2-ui-agent-0713`、`step1-rag-agent-1783650562`、`T10 Context Agent`、`T09 QA Agent` 等。
- Knowledge bases:
  - `示例知识库：合同审批`, type=`faq`, status=`active`, embedding_model=`mock-embedding`
  - 另有既有测试知识库：`Vue 测试知识库0713-1`、`前端测试知识库`、`T10上下文知识库`、`T09知识库` 等。
- Tools:
  - `12345问数`, type=`builtin`, status=`active`, builtin=`nl2data`
  - `calculator`, `python_sum`, `backend_health`, `T09计算器`, `T10计算器`
- Models:
  - active mock LLM: `mock-chat`, `mock-chat-0713`, `manual-regression-1783841277`, `ui-mock-0712`, `mc-mock-*`, `mock-chat-limit`, `mock-chat-t04`, 等。
  - active mock embedding: `mock-embedding`

## 问题记录

1. `SEED_DEMO_MODE=true` 没有传进 backend 容器内的 `seed_examples.py` 执行环境。
   - 证据：quickstart 输出 `SEED_DEMO_MODE is not true; skip mock/demo example seed.`
   - 影响：从空库启动时，demo 示例 Agent/知识库/工具可能不会按预期写入。
   - 本次未修正代码。

2. `seed_model_catalog.py` 同样依赖容器内 `SEED_DEMO_MODE`，本次执行后 `model_catalog` 中 `mock-chat` 和 `mock-embedding` 仍为 `is_active=false`。
   - 影响：模型目录页可能看不到 active 的 mock catalog 项。
   - 当前 demo 链路能走通，是因为数据库已有历史 runtime mock 模型和 MaaS 渠道。
   - 本次未修正代码。

3. 当前数据库不是全新 demo 基线，包含多轮历史测试数据。
   - 影响：后续测试需要明确区分 seed 示例数据与历史测试数据，避免误判。
   - 本次未清库、未改数据。

## 环境就绪确认

结论：可以进入 Step 1，但需带着上述基线 caveat。

理由：

- backend、maas、sandbox、frontend 均可达。
- postgres、redis、minio 处于 compose healthy。
- 管理员登录成功，token 已保存。
- MaaS 实际 `PRODUCTION_MODE=false`。
- active mock LLM/embedding 渠道存在。
- `/v1/chat/completions` 已返回 `mock response: ping`。
- `/v1/embeddings` 已返回 1536 维 mock embedding。

风险：

- 这不是纯净 demo seed 环境；quickstart 的 `SEED_DEMO_MODE` 传递存在问题，后续测试若要求空库可复现，需要单独记录该问题并等待修复或明确重置策略。
