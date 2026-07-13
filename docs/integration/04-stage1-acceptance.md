# 阶段 1 验收记录

## 范围

阶段 1 搭建 `cockpit-service` 骨架，并打通“前端菜单 → nginx → cockpit → 数据库”的部署链路。

## 已完成

### 服务骨架

- 新增 `cockpit/`：
  - FastAPI 入口：`cockpit/app/main.py`
  - 配置：`cockpit/app/core/config.py`
  - 数据库 session：`cockpit/app/core/database.py`
  - JWT 鉴权：`cockpit/app/core/auth.py`
  - 健康接口：`GET /api/v1/health`
  - 当前用户接口：`GET /api/v1/me`
  - BFF 客户端骨架：`cockpit/app/clients/wanwu_bff.py`
  - Alembic 首迁移：`cockpit/alembic/versions/0001_create_cockpit_meta.py`

### 部署编排

- 新增 `docker-compose.cockpit.yaml`
- `cockpit-postgres` 使用 `pgvector/pgvector:pg15`，不暴露宿主机端口。
- `cockpit-service` build `./cockpit`，加入外部网络 `wanwu-net`。
- `cockpit-service` 启动命令为 `alembic upgrade head && uvicorn ...`。
- Compose 静态解析已通过，能解析出 `cockpit-postgres` 与 `cockpit-service`。

组合启动命令：

```bash
docker network create wanwu-net
docker compose --env-file wanwu/.env --env-file wanwu/.env.ontology --env-file wanwu/.env.image.arm64 -f wanwu/docker-compose.yaml -f docker-compose.cockpit.yaml up -d
```

### nginx 与前端

- nginx 新增 `/cockpit/api/` 反向代理到 `cockpit-service:18081/api/`。
- 前端新增 `/cockpit` 路由和“驾驶舱”菜单。
- 前端新增独立 `cockpit.js` API 客户端，复用 token 注入，但不信任 `x-user-id`。
- 阶段 1 临时让“驾驶舱”菜单对所有登录用户可见。TODO：阶段 7 接入 IAM 权限点。

## 已验证

- Python 静态编译：`python3 -m compileall -q cockpit/app cockpit/alembic` 通过。
- Compose 配置解析：`docker compose ... config --services` 通过，并包含 `cockpit-postgres`、`cockpit-service`。
- JWT 代码路径确认：cockpit 只从 JWT claims `userId` 读取可信身份；`x-org-id` 只作为组织上下文。

## 未完成运行验收

当前环境仍无法访问 Docker daemon socket，因此不能实际启动容器、访问浏览器或查询数据库：

```text
permission denied while trying to connect to the Docker daemon socket at unix:///Users/wangsiyi/.docker/run/docker.sock
```

此外，`wanwu/web/node_modules` 当前不存在，且本环境网络受限，未执行前端生产构建；前端变更已完成源码级检查。

以下验收项待在具备 Docker 权限的环境补验：

1. 组合启动后所有容器 healthy。
2. 浏览器登录 wanwu，侧边栏出现“驾驶舱”，页面显示当前 `user_id` 与 `org_id`。
3. `curl http://localhost:8081/cockpit/api/v1/me` 不带 token 返回 401。
4. 仅带伪造 `x-user-id`、无有效 token 请求 `/cockpit/api/v1/me` 返回 401。
5. `cockpit-postgres` 中存在 `cockpit_meta` 表。

## 补验命令

```bash
curl -i http://localhost:8081/cockpit/api/v1/health
curl -i http://localhost:8081/cockpit/api/v1/me
curl -i -H 'x-user-id: forged' http://localhost:8081/cockpit/api/v1/me
docker exec cockpit-postgres psql -U cockpit -d cockpit -c '\\dt'
```

带有效 token 验证：

```bash
curl -i \
  -H "Authorization: Bearer <wanwu_login_token>" \
  -H "x-org-id: <current_org_id>" \
  http://localhost:8081/cockpit/api/v1/me
```

## 问题与处理

- 问题：蓝图阶段 0 推荐的“信任转发用户头”存在客户端伪造风险。
- 处理：阶段 1 改为 cockpit 自行校验 wanwu HS256 JWT，`x-org-id` 不作为身份凭据。
- 问题：本执行环境无 Docker daemon 权限。
- 处理：完成源码、配置、Compose 静态解析与文档，运行验收待有权限环境补验。
