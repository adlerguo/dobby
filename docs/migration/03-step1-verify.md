# Step 1 Verify: Model Hub Data Migration

本步骤只验证模型纳管数据模型迁移：

- 新增 `models` 元信息列。
- 同步 `backend` ORM 和 `maas` Table 定义。
- 不验证任何新 API，因为 Step 1 未新增接口。

## 1. 起依赖和服务

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

docker compose up -d postgres redis minio sandbox
docker compose up -d --build maas backend
```

说明：本步骤新增了 Alembic 迁移文件，并同步修改了 `backend` 和 `maas` 的模型定义。必须重建 `backend` 镜像，否则容器内的 `/app/alembic/versions` 仍可能是旧文件列表，`alembic upgrade head` 会看不到新迁移。

健康检查：

```bash
curl -s http://localhost:8001/healthz
curl -s http://localhost:8100/healthz
curl -s http://localhost:8200/healthz
```

期望分别看到 backend、maas、sandbox 的 `status: ok`。

## 2. 执行迁移

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent

docker compose exec backend alembic upgrade head
```

## 3. 确认新列存在

```bash
docker compose exec postgres psql -U app -d eap -c '\d models'
```

期望至少能看到这些列：

- `display_name`
- `description`
- `is_active`
- `provider_config`
- `import_source`
- `model_icon_path`
- `publish_date`
- `scope_type`
- `created_at`
- `updated_at`

也可以用 SQL 精确检查：

```bash
docker compose exec postgres psql -U app -d eap -c "
select column_name
from information_schema.columns
where table_name = 'models'
  and column_name in (
    'display_name',
    'description',
    'is_active',
    'provider_config',
    'import_source',
    'model_icon_path',
    'publish_date',
    'scope_type',
    'created_at',
    'updated_at'
  )
order by column_name;
"
```

## 4. 确认存量模型还在且老接口可读

先确保默认账号存在：

```bash
docker compose exec backend python -m app.scripts.seed
```

登录并读取老接口 `/api/v1/models`：

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8001/api/v1/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

期望：

- 请求正常返回 JSON 数组。
- 仍能看到已有模型，例如 `mock-chat`、`mock-embedding`，如果你之前配置过，也应能看到 `siyids测试模型`。
- 返回结构仍保持老接口兼容：`id/name/provider/type`。

## 5. 确认 MaaS 没被搞挂

```bash
curl -s http://localhost:8100/v1/models | python3 -m json.tool
```

期望：

- 正常返回模型数组。
- MaaS 服务没有因为 `models` 表新增列崩溃。

也可以做一次 mock chat：

```bash
curl -s -X POST http://localhost:8100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mock-chat","messages":[{"role":"user","content":"ping"}]}' \
  | python3 -m json.tool
```

期望能返回 `mock response: ping`。

## 6. 确认可回滚，再升回

先回滚一版：

```bash
docker compose exec backend alembic downgrade -1
```

确认新列消失：

```bash
docker compose exec postgres psql -U app -d eap -c '\d models'
```

期望看不到：

- `display_name`
- `is_active`
- `provider_config`
- `import_source`
- `scope_type`
- `created_at`
- `updated_at`

再升回最新：

```bash
docker compose exec backend alembic upgrade head
```

再次确认新列回来：

```bash
docker compose exec postgres psql -U app -d eap -c '\d models'
```

## 7. 验证失败时的定位命令

查看 backend 迁移日志：

```bash
docker compose logs --tail=120 backend
```

查看 maas 是否因表定义异常退出：

```bash
docker compose logs --tail=120 maas
```

查看当前 Alembic 版本：

```bash
docker compose exec backend alembic current
docker compose exec backend alembic history --verbose | tail -80
```
