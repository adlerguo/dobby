# 12 Step 1：model_catalog 表与首批目录 Seed 验证

本步骤验证：

1. 只新增 `model_catalog` 一张表，不改现有 `models/model_channels/agents`。
2. 目录表不含 API Key 字段，不含 tenant 字段。
3. seed 首批目录数据，且可重复执行不重复插入。
4. 现有模型列表和 MaaS 模型列表不受影响。

## 0. 重建 backend 并升级迁移

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build backend postgres maas redis
docker compose exec backend alembic upgrade head
```

期望：

- alembic 输出里能看到类似：

```text
Running upgrade 202607100002 -> 202607100003, add model catalog
```

如果没有看到 Running upgrade，先执行：

```bash
docker compose exec backend alembic history --verbose | tail -80
docker compose exec backend alembic current
```

确认 `202607100003` 在 migration 链上。

## 1. 确认表结构

```bash
docker compose exec postgres psql -U app -d eap -c '\d model_catalog'
```

期望字段：

- `id`
- `provider`
- `model_code`
- `display_name`
- `model_type`
- `description`
- `context_window`
- `supports_streaming`
- `supports_tools`
- `supports_vision`
- `default_base_url`
- `protocol`
- `recommended_parameters`
- `official_url`
- `pricing`
- `icon`
- `sort_order`
- `is_active`
- `created_at`
- `updated_at`

确认没有密钥和租户字段：

```bash
docker compose exec postgres psql -U app -d eap -c "
select column_name
from information_schema.columns
where table_name='model_catalog'
  and (
    column_name ilike '%key%'
    or column_name ilike '%secret%'
    or column_name ilike '%token%'
    or column_name='tenant_id'
  )
order by column_name;
"
```

期望：

```text
(0 rows)
```

## 2. 执行 seed

```bash
docker compose exec backend python -m app.scripts.seed_model_catalog
```

查询首批目录：

```bash
docker compose exec postgres psql -U app -d eap -c "
select provider, model_code, display_name, model_type, protocol, default_base_url, recommended_parameters->>'availability' as availability
from model_catalog
order by sort_order, provider, model_code;
"
```

期望至少包含 7 条：

- `mock / mock-chat / llm / mock / availability=verified_local`
- `mock / mock-embedding / embedding / mock / availability=verified_local`
- `deepseek / deepseek-chat / llm / openai_compatible / availability=needs_real_key`
- `deepseek / deepseek-reasoner / llm / openai_compatible / availability=needs_real_key`
- `openai / gpt-4o-mini / llm / openai_compatible / availability=needs_real_key`
- `openai / text-embedding-3-small / embedding / openai_compatible / availability=needs_real_key`
- `qwen / qwen-plus / llm / openai_compatible / availability=needs_real_key`

## 3. 验证 seed 幂等

记录第一次数量：

```bash
COUNT_BEFORE=$(docker compose exec -T postgres psql -U app -d eap -t -A -c "select count(*) from model_catalog;")
echo "COUNT_BEFORE=$COUNT_BEFORE"
```

再跑 seed：

```bash
docker compose exec backend python -m app.scripts.seed_model_catalog
```

记录第二次数量：

```bash
COUNT_AFTER=$(docker compose exec -T postgres psql -U app -d eap -t -A -c "select count(*) from model_catalog;")
echo "COUNT_AFTER=$COUNT_AFTER"
test "$COUNT_BEFORE" = "$COUNT_AFTER" && echo "seed idempotent ok"
```

期望：

- 第二次 seed 不报错。
- `COUNT_BEFORE` 等于 `COUNT_AFTER`。
- 输出 `seed idempotent ok`。

确认 `model_code` 没重复：

```bash
docker compose exec postgres psql -U app -d eap -c "
select model_code, count(*)
from model_catalog
group by model_code
having count(*) > 1;
"
```

期望：

```text
(0 rows)
```

## 4. 回归现有模型表和接口

登录拿 token：

```bash
ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

现有内部模型下拉接口：

```bash
curl -s http://localhost:8001/api/v1/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

模型纳管接口：

```bash
curl -s http://localhost:8001/api/v1/model-hub/models \
  -H "Authorization: Bearer $ACCESS" \
  | python3 -m json.tool
```

MaaS 模型接口：

```bash
curl -s http://localhost:8100/v1/models \
  | python3 -m json.tool
```

期望：

- 三个接口仍正常返回。
- `model_catalog` seed 不会自动污染 `models` 运行表。
- 现有 `mock-chat`、`mock-embedding` 等模型仍正常。

确认 `models` 表未新增 `catalog_id`：

```bash
docker compose exec postgres psql -U app -d eap -c "
select column_name
from information_schema.columns
where table_name='models' and column_name='catalog_id';
"
```

期望：

```text
(0 rows)
```

## 5. 回滚验证

回滚一版：

```bash
docker compose exec backend alembic downgrade -1
```

确认表消失：

```bash
docker compose exec postgres psql -U app -d eap -c "
select to_regclass('public.model_catalog') as model_catalog_table;
"
```

期望：

```text
model_catalog_table
---------------------

```

或返回空值。

再升级回来：

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed_model_catalog
```

确认目录数据恢复：

```bash
docker compose exec postgres psql -U app -d eap -c "
select provider, model_code, model_type, protocol
from model_catalog
order by sort_order, provider, model_code;
"
```

## 6. 本步新增文件

```text
backend/alembic/versions/202607100003_model_catalog.py
backend/app/scripts/seed_model_catalog.py
docs/migration/12-step1-model-catalog-verify.md
```

本步还同步了 backend ORM：

```text
backend/app/models/entities.py
backend/app/models/__init__.py
```
