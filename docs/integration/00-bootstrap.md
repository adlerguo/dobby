# 阶段 0 启动记录

## 目标

按 `wanwu/README_CN.md` 的 Docker 安装路径启动万悟底座，并记录配置、验证结果与阻断项。

## 已完成配置

源码依据：

- 快速启动要求复制 `.env.example`、配置 `WANWU_ARCH`、`WANWU_EXTERNAL_IP`、`WANWU_BFF_JWT_SIGNING_KEY`，再复制 `.env.ontology.example`：`wanwu/README_CN.md`
- 主编排文件包含 `docker-compose.ontology.yaml`：`wanwu/docker-compose.yaml`
- BFF 容器通过环境变量 `JWT_SIGNING_KEY: ${WANWU_BFF_JWT_SIGNING_KEY}` 注入 JWT 密钥：`wanwu/docker-compose.yaml`

本机检测结果：

- CPU 架构：`arm64`
- Docker CLI：存在
- Docker Compose：存在

已生成运行配置：

- `wanwu/.env`：由 `wanwu/.env.example` 复制生成
- `wanwu/.env.ontology`：由 `wanwu/.env.ontology.example` 复制生成
- `WANWU_ARCH=arm64`
- `WANWU_EXTERNAL_IP=localhost`
- `WANWU_EXTERNAL_PORT=8081`
- `WANWU_BFF_JWT_SIGNING_KEY` 已写入 64 位 hex 随机串

## Compose 服务解析结果

`docker compose --env-file .env --env-file .env.ontology --env-file .env.image.arm64 config --services` 可正常解析，服务列表包括：

`mysql`、`redis`、`minio`、`kafka`、`es`、`bff-service`、`iam-service`、`model-service`、`mcp-service`、`knowledge-service`、`rag-service`、`assistant-service`、`agent-service`、`operate-service`、`app-service`、`channel-service`、`callback`、`workflow`、`rag`、`wga-sandbox`、`nginx`，以及本体相关 `data-connection`、`vega-gateway`、`vega-backend`、`vega-gateway-pro`、`mdl-data-model`、`mdl-uniquery`、`vega-calculate-coordinator`、`ontology-query`、`agent`、`bkn-backend`、`web`、`wga-sandbox-ontology`。

## 启动阻断

未能实际创建 Docker 网络或启动容器。原因是当前执行环境无法访问本机 Docker daemon socket：

```text
permission denied while trying to connect to the Docker daemon socket at unix:///Users/wangsiyi/.docker/run/docker.sock
```

因此以下验收项本轮无法完成，均不能写成已验证：

- 所有容器 healthy
- 浏览器访问 `http://localhost:8081`
- 注册/登录
- 创建知识库并上传文档完成解析
- 创建简单智能体并对话

## 后续补验命令

在有 Docker daemon 访问权限的终端中进入 `wanwu/` 后执行：

```bash
docker network create wanwu-net
docker compose --env-file .env --env-file .env.ontology --env-file .env.image.arm64 up -d
docker compose --env-file .env --env-file .env.ontology --env-file .env.image.arm64 ps
```

登录地址：

- `http://localhost:8081`
- 默认用户：`admin`
- 默认密码：`Wanwu123456`

若 Linux 上 ES 报 `Memory limited without swap`，README 建议执行 `sudo sysctl -w vm.max_map_count=262144` 后重启；该说明来自 `wanwu/README_CN.md` 的 Q&A。

