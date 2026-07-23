#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "启动 6qiyeagent 全栈服务..."
docker compose up -d --build postgres redis minio maas sandbox backend frontend

echo "等待 backend 就绪..."
backend_ready=false
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8001/healthz >/dev/null 2>&1; then
    backend_ready=true
    break
  fi
  sleep 2
done
if [[ "$backend_ready" != "true" ]]; then
  echo "backend 在 120 秒内未就绪。请按以下命令排查："
  echo "- docker compose ps"
  echo "- docker compose logs backend"
  echo "- curl -v http://localhost:8001/healthz"
  exit 1
fi

echo "执行数据库迁移..."
docker compose exec -T backend alembic upgrade head

echo "写入默认租户、管理员和权限种子..."
docker compose exec -T backend python -m app.scripts.seed

echo "写入模型目录..."
docker compose exec -T backend python -m app.scripts.seed_model_catalog

if [[ "${SEED_DEMO_MODE:-}" =~ ^(1|true|TRUE|yes|YES)$ ]]; then
  echo "SEED_DEMO_MODE=true，写入显式演示数据..."
  docker compose exec -T -e SEED_DEMO_MODE="${SEED_DEMO_MODE}" backend python -m app.scripts.seed_examples
else
  echo "未开启 SEED_DEMO_MODE：跳过 mock 演示数据，默认引导配置真实模型。"
fi

echo
echo "启动完成："
echo "- 前端: http://localhost:18080"
echo "- Backend: http://localhost:8001/healthz"
echo "- MaaS: http://localhost:8100/healthz"
echo "- Sandbox: http://localhost:8200/healthz"
echo
echo "默认登录：default / admin / Admin123!"
echo "建议先打开 http://localhost:18080/quickstart 按向导配置真实模型 API。"
