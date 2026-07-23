import os
import secrets
import sys
from pathlib import Path


WEAK_SECRET_VALUES = {"change-me", "change-me-32-byte-key", ""}


def resolve_runtime_secret(
    *, env_name: str, file_name: str, label: str, configured_value: str | None = None
) -> str:
    env_value = (
        configured_value if configured_value is not None else os.getenv(env_name)
    )
    if env_value is not None:
        return validate_runtime_secret(
            env_value, env_name=env_name, label=label, source="环境变量或 .env"
        )

    secret_file = configured_secret_file(env_name=env_name, file_name=file_name)
    if secret_file.exists():
        return validate_runtime_secret(
            secret_file.read_text(encoding="utf-8").strip(),
            env_name=env_name,
            label=label,
            source=f"密钥文件 {secret_file}",
        )

    if os.getenv("AUTO_GENERATE_SECRETS", "").lower() not in {"1", "true", "yes"}:
        print(
            f"[安全配置错误] {label} 未配置，且未找到密钥文件 {secret_file}。服务已拒绝启动。\n"
            f"处理方式：\n"
            f"1. 已有部署必须设置原 {env_name}，或把原密钥写入 {secret_file}；\n"
            f"2. 仅全新部署可设置 AUTO_GENERATE_SECRETS=true 允许首次自动生成；\n"
            f"3. 不允许在已有加密数据的实例上静默生成新密钥。",
            file=sys.stderr,
        )
        sys.exit(1)

    secret = secrets.token_urlsafe(48)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(secret + "\n", encoding="utf-8")
        secret_file.chmod(0o600)
    except OSError as exc:
        print(
            f"[安全配置错误] {label} 未配置，且无法在 {secret_file} 首次生成密钥：{exc}。"
            f"请设置 {env_name}，或挂载可写的 APP_SECRETS_DIR=/data/secrets。",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[安全配置] 已首次生成 {label} 并持久化到 {secret_file}。请妥善备份该文件。")
    return secret


def configured_secret_file(*, env_name: str, file_name: str) -> Path:
    explicit_file = os.getenv(f"{env_name}_FILE")
    if explicit_file:
        return Path(explicit_file)
    return Path(os.getenv("APP_SECRETS_DIR", "/data/secrets")) / file_name


def validate_runtime_secret(
    value: str | None, *, env_name: str, label: str, source: str
) -> str:
    normalized = (value or "").strip()
    if normalized in WEAK_SECRET_VALUES:
        print(
            f"[安全配置错误] {label} 来自{source}，但值为空或属于已知弱默认值。服务已拒绝启动。\n"
            f"处理方式：\n"
            f"1. 生产环境请设置随机的 {env_name}；\n"
            f"2. Docker 部署可删除弱值并挂载 /data/secrets，让系统首次启动自动生成；\n"
            f"3. 已有加密数据的实例必须继续使用原密钥，不能随意更换。",
            file=sys.stderr,
        )
        sys.exit(1)
    return normalized
