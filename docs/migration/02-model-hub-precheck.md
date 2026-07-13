# Model Hub Step 0.5 Precheck

本文件是进入 Step 1 前的预检结论。范围：只查代码和配置，不改业务代码、不写迁移。

## 1. 风险 1：双表定义问题

### 1.1 结论

`backend` 服务和 `maas` 服务连接的是同一个 Postgres 数据库里的同一组物理表：`models`、`model_channels`。

因此 Step 1 迁移时必须遵守：

- 只由 `backend/alembic` 负责建表和变更表结构。
- `backend/app/models/entities.py` 的 ORM 定义和 `maas/app/models.py` 的 Table 定义都要同步新增字段。
- 字段应尽量做可空或有默认值，避免 MaaS 旧读写路径因为缺必填字段崩溃。
- MaaS 没有 Alembic，不应在 MaaS 里创建独立迁移。

### 1.2 DATABASE_URL 证据

| 服务 | 证据路径 | 结论 |
|---|---|---|
| backend 默认数据库 | `backend/app/core/config.py` | `database_url` 默认值是 `postgresql+psycopg://app:pass@postgres:5432/eap` |
| backend 实际建 engine | `backend/app/core/database.py` | `create_async_engine(settings.database_url)` |
| maas 默认数据库 | `maas/app/core/config.py` | `database_url` 默认值也是 `postgresql+psycopg://app:pass@postgres:5432/eap` |
| maas 实际建 engine | `maas/app/core/database.py` | `create_async_engine(settings.database_url)` |
| compose 注入 backend DATABASE_URL | `docker-compose.yml` | `DATABASE_URL: ${DATABASE_URL:-postgresql+psycopg://app:pass@postgres:5432/eap}` |
| compose 注入 maas DATABASE_URL | `docker-compose.yml` | 同样是 `DATABASE_URL: ${DATABASE_URL:-postgresql+psycopg://app:pass@postgres:5432/eap}` |
| compose Postgres 库名 | `docker-compose.yml` | `POSTGRES_DB: ${POSTGRES_DB:-eap}` |

### 1.3 谁负责迁移

| 项 | 证据路径 | 结论 |
|---|---|---|
| backend 有 Alembic | `backend/alembic.ini`、`backend/alembic/env.py` | `backend/alembic/env.py` 使用 `settings.database_url` 并以 `Base.metadata` 为目标 metadata |
| backend Dockerfile 包含 Alembic 文件 | `backend/Dockerfile` | 镜像会复制 `alembic.ini` 和 `alembic/` |
| maas 无 Alembic | `maas/Dockerfile`、`maas/requirements.txt` | MaaS 只安装 SQLAlchemy/psycopg，无 alembic 文件和依赖 |

结论：`backend/alembic` 是唯一迁移入口。

### 1.4 两套定义当前是否一致

当前两套定义在基础字段上基本一致，但不是同一种声明方式：

| 表 | backend ORM | maas Table | 当前一致性 |
|---|---|---|---|
| `models` | `backend/app/models/entities.py` 的 `Model` | `maas/app/models.py` 的 `models = Table(...)` | 都有 `id/name/provider/type` |
| `model_channels` | `backend/app/models/entities.py` 的 `ModelChannel` | `maas/app/models.py` 的 `model_channels = Table(...)` | 都有 `id/tenant_id/model_id/base_url/api_key_enc/weight/rpm_limit/status/health/created_at` |

字段行证据：

- `backend/app/models/entities.py`: `Model` 在 205 行附近，`ModelChannel` 在 213 行附近。
- `maas/app/models.py`: `models = Table` 在 17 行附近，`model_channels = Table` 在 26 行附近。
- 初始建表在 `backend/alembic/versions/202607070001_init_data_layer.py`，`models` 表在 205 行附近，`model_channels` 表在 215 行附近。

### 1.5 Step 1 同步策略

如果 Step 1 给 `models` 加字段：

1. 新增 Alembic 迁移只放在 `backend/alembic/versions/`。
2. 同步更新 `backend/app/models/entities.py` 的 `Model` ORM。
3. 同步更新 `maas/app/models.py` 的 `models = Table(...)`。
4. 先不强制 MaaS 使用所有新字段，但要让 MaaS 查询 `select(models)` 时能识别表结构。
5. 不改 `model_channels` 字段，除非 Step 1 明确需要渠道级字段；本模块首版优先把模型元信息放在 `models`。

建议 Step 1 新字段全部可空或有默认值：

- `display_name text`
- `description text`
- `is_active bool default true`
- `provider_config jsonb default '{}'`
- `import_source text default 'external'`
- `model_icon_path text`
- `publish_date text`
- `scope_type text default 'tenant'`
- `created_at timestamptz default now()`
- `updated_at timestamptz default now()`

## 2. 风险 2：新老接口关系

### 2.1 结论

保留老接口 `/api/v1/models`，新增纳管接口 `/api/v1/model-hub/models`。

两者定位不同：

| 接口 | 角色 | 是否改造 |
|---|---|---|
| `GET /api/v1/models` | 老兼容接口，给智能体创建页模型下拉使用 | 保留，只读，首轮不破坏返回结构 |
| `/api/v1/model-hub/models` | 新模型纳管接口，负责 CRUD、启停、渠道概览 | 新增 |

### 2.2 证据

| 事实 | 证据路径 | 说明 |
|---|---|---|
| 老 `/models` 当前定义在 agents router | `backend/app/api/v1/agents.py` | `@router.get("/models", response_model=list[ModelOut])` |
| 老返回结构很薄 | `backend/app/schemas/agents.py` | `ModelOut` 只有 `id/name/provider/type` |
| 智能体创建页依赖老接口 | `frontend/src/views/AgentListView.vue` | `loadData()` 调 `apiFetch<Model[]>('/models')` 并填充模型下拉 |
| 智能体创建提交使用 `model_id` | `frontend/src/views/AgentListView.vue` | `createAgent()` body 里传 `model_id` |

### 2.3 Step 3 前端切换策略

Step 3 不强制切换智能体创建页的模型下拉。

推荐策略：

1. 新增 `ModelHubView.vue` 使用 `/model-hub/models`。
2. `AgentListView.vue` 继续调用 `/models`，避免影响智能体创建闭环。
3. 在 Step 4 联调通过后，再评估是否让智能体下拉切换到 `/model-hub/models?is_active=true&model_type=llm`。
4. 如果切换，也要保证前端类型 `Model` 仍兼容 `id/name/provider/type`。

### 2.4 运行时关系

智能体运行仍依赖现有模型名调用 MaaS：

- `backend/app/orchestrator/runtime.py` 会加载 `Model`，然后用 `model.name` 调用 MaaS。
- 因此新模型纳管不能随意重命名 `name` 的语义。`name` 应继续代表系统内部逻辑模型名/调用名；`display_name` 才是页面展示名。

## 3. 风险 3：本地可运行前提

### 3.1 结论

后续每步验证可以用两种方式：

1. Docker Compose 全量运行：最稳定，服务内部使用 `postgres:5432`、`redis:6379`、`maas:8100`、`sandbox:8200`。
2. 本机 uvicorn 运行 backend/maas：可以，但必须先启动依赖容器，并覆盖连接地址为本机端口。

### 3.2 Docker Compose 运行前提

`docker-compose.yml` 已定义：

- `postgres`: 暴露 `5432:5432`
- `redis`: 暴露 `6379:6379`
- `minio`: 暴露 `9000:9000` 和 `9001:9001`
- `backend`: 暴露 `8001:8001`
- `maas`: 暴露 `8100:8100`
- `sandbox`: 暴露 `8200:8200`
- `frontend`: 暴露 `18080:80`

验证时推荐先跑：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build
```

注意：`backend/Dockerfile` 的启动命令只是：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

证据：`backend/Dockerfile`。

它不会自动执行：

- `alembic upgrade head`
- `python -m app.scripts.seed`

所以后续 Step 1 如果新增迁移，验证命令必须显式执行迁移。

### 3.3 本机 uvicorn 运行前提

如果不用容器跑 backend/maas，而是在本机运行：

backend 需要把服务内地址改成本机地址：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent/backend
DATABASE_URL=postgresql+psycopg://app:pass@localhost:5432/eap \
REDIS_URL=redis://localhost:6379/0 \
MINIO_ENDPOINT=localhost:9000 \
MAAS_BASE_URL=http://localhost:8100 \
SANDBOX_BASE_URL=http://localhost:8200 \
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

maas 需要：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent/maas
DATABASE_URL=postgresql+psycopg://app:pass@localhost:5432/eap \
REDIS_URL=redis://localhost:6379/0 \
MAAS_ENCRYPTION_KEY=change-me-32-byte-key \
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

证据：

- `backend/app/core/config.py`
- `maas/app/core/config.py`
- `backend/app/core/database.py`
- `maas/app/core/database.py`

### 3.4 登录账号来源

默认登录账号来自 seed 脚本，不是硬编码在登录接口里。

| 项 | 证据路径 | 说明 |
|---|---|---|
| seed 入口 | `backend/app/scripts/seed.py` | 调用 `ensure_default_seed(db)` 并提交 |
| 默认租户 | `backend/app/services/rbac_service.py` | `Tenant(name="默认租户", code="default", status="active")` |
| 默认用户 | `backend/app/services/rbac_service.py` | `username="admin"`，`password_hash=hash_password("Admin123!")` |
| 默认角色 | `backend/app/services/rbac_service.py` | 给 admin 分配 `super_admin` |
| 登录接口 | `backend/app/api/v1/auth.py` | 根据 `tenant_code`、`username`、`password_hash` 校验 |

后续如果数据库是新库或被清空，需要先执行：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent/backend
DATABASE_URL=postgresql+psycopg://app:pass@localhost:5432/eap \
python -m app.scripts.seed
```

如果在容器内执行：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose exec backend python -m app.scripts.seed
```

### 3.5 后续所有步骤的最小前置

推荐后续每一步验证前使用这组前置命令：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

docker compose up -d postgres redis minio maas sandbox backend

docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed

curl -s http://localhost:8001/healthz
curl -s http://localhost:8100/healthz

ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8001/api/v1/auth/me \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

如果这些命令通过，再开始 Step 1/2/3 的真实验证。

## 4. Step 1 前的执行结论

可以进入 Step 1，但 Step 1 必须按下面边界执行：

1. 只在 `backend/alembic/versions/` 新增迁移，由 backend 负责改物理表。
2. 同步更新 `backend/app/models/entities.py` 和 `maas/app/models.py`。
3. 不改变 `/api/v1/models` 现有返回结构。
4. 不改变 MaaS `/v1/chat/completions` 和 `/v1/embeddings` 调用逻辑。
5. 新字段先可空或带默认值，避免已有模型、渠道、调用链断裂。

## 5. Step 0.5 本地验证命令

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

test -f docs/migration/02-model-hub-precheck.md && echo "precheck doc ok"
grep -n "风险 1" docs/migration/02-model-hub-precheck.md
grep -n "风险 2" docs/migration/02-model-hub-precheck.md
grep -n "风险 3" docs/migration/02-model-hub-precheck.md
```

