# cockpit-service

cockpit-service 是挂载在 wanwu 底座上的增量微服务，用于承载智能体驾驶舱、评测与经验库等后续能力。

## 技术栈

- Python 3.12
- FastAPI
- SQLAlchemy 2.0 async
- Alembic
- PostgreSQL + pgvector 镜像

## 鉴权约定

服务通过 `JWT_SIGNING_KEY` 共享 wanwu BFF 的 HS256 JWT 密钥，自行校验：

- `Authorization: Bearer <token>` 必须存在
- `issuer` 必须为 `wanwu`
- `subject` 必须为 `user`
- 只信任 JWT claims 中的 `userId` 作为用户身份
- `x-org-id` 仅作为组织上下文读取，不作为身份凭据

cockpit-service 不暴露宿主机端口，只加入 `wanwu-net`，由 wanwu nginx 通过 `/cockpit/api/` 反向代理访问。

## 本地容器启动

从仓库根目录启动：

```bash
docker compose --env-file wanwu/.env --env-file wanwu/.env.ontology --env-file wanwu/.env.image.arm64 -f wanwu/docker-compose.yaml -f docker-compose.cockpit.yaml up -d
```

容器启动时会先执行 `alembic upgrade head`，再启动 `uvicorn`。

