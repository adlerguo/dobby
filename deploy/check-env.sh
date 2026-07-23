#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-${APP_ENV:-development}}"
PRODUCTION=false
if [[ "$MODE" =~ ^(prod|production)$ ]]; then
  PRODUCTION=true
fi

failures=()

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    failures+=("$name 未设置")
  fi
}

reject_weak() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" ]]; then
    return
  fi
  if [[ "$value" == "pass" || "$value" == "minioadmin" || "$value" =~ ^dev-.*-token ]]; then
    failures+=("$name 使用了开发弱口令或默认 token")
  fi
}

if $PRODUCTION; then
  for name in POSTGRES_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD MINIO_KEY MINIO_SECRET MAAS_ADMIN_TOKEN JWT_SECRET DATABASE_URL REDIS_URL; do
    require_var "$name"
  done
fi

for name in POSTGRES_PASSWORD MINIO_ROOT_PASSWORD MINIO_KEY MINIO_SECRET MAAS_ADMIN_TOKEN JWT_SECRET; do
  reject_weak "$name"
done

if ((${#failures[@]} > 0)); then
  echo "环境检查失败："
  for item in "${failures[@]}"; do
    echo "- $item"
  done
  exit 1
fi

echo "环境检查通过。"
