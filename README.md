# 6qiyeagent

6qiyeagent 是一个企业智能体中台示例工程，包含管理后台、后端 API、MaaS 模型服务、代码沙箱，以及 Postgres、Redis、MinIO 基础依赖。项目用于快速完成模型接入、知识库构建、智能体创建、对话验证、发布和审计观测。

## 服务与端口

| 服务 | 默认端口 | 说明 |
|---|---:|---|
| frontend | 18080 | 前端控制台 |
| backend | 8001 | FastAPI 管理后台与公开 API |
| maas | 8100 | 模型渠道管理与调用代理 |
| sandbox | 8200 | 工具执行沙箱 |
| postgres | 5432 | 业务数据库 |
| redis | 6379 | 缓存、限速与配额 |
| minio | 9000/9001 | 文档对象存储与控制台 |

生产部署请参考 `docker-compose.prod.example.yml`，不要暴露数据库、Redis、MinIO、MaaS、Sandbox 的宿主机端口。

## 快速启动

```bash
bash deploy/quickstart.sh
```

启动完成后访问：

- 前端控制台：`http://localhost:18080`
- 后端健康检查：`http://localhost:8001/healthz`

默认账号信息见内部文档：`docs/交付内部文档/默认账号与初始化说明.md`。对外材料不要写明文默认密码。

## 目录结构

| 路径 | 说明 |
|---|---|
| `backend/` | FastAPI 后端、迁移、业务服务 |
| `frontend/` | Vue3 管理后台 |
| `maas/` | 模型渠道服务 |
| `sandbox/` | 工具执行沙箱 |
| `docs/` | 操作、商业化、开发者和内部交付文档 |
| `deploy/` | 启动与环境检查脚本 |

## 常用命令

```bash
docker compose ps
docker compose logs -f backend
docker compose exec -T backend alembic upgrade head
cd frontend && npm run build
python -m compileall backend/app
```

## 第一次修改指引

1. 先复制 `.env` 或在部署平台配置环境变量。
2. 生产模式先执行 `bash deploy/check-env.sh production`。
3. 修改默认账号密码，并为客户创建正式管理员账号。
4. 到模型中心接入真实 LLM 和 embedding 模型。
5. 创建知识库并上传小样本文档，确认解析、检索和引用正常。

## 验证命令

```bash
bash -n deploy/check-env.sh && bash -n deploy/quickstart.sh
docker compose ps
curl -fsS http://localhost:8001/healthz
curl -fsS http://localhost:18080
```
