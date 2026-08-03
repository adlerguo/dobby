from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secrets import resolve_runtime_secret


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Enterprise AI Platform Backend"
    app_version: str = "0.1.0"
    service_name: str = "backend"

    database_url: str = Field(default="postgresql+psycopg://app:pass@postgres:5432/eap")
    redis_url: str = Field(default="redis://redis:6379/0")
    minio_endpoint: str = Field(default="minio:9000")
    minio_key: str = Field(default="minioadmin")
    minio_secret: str = Field(default="minioadmin")
    minio_bucket: str = Field(default="eap-documents")
    minio_secure: bool = Field(default=False)
    maas_base_url: str = Field(default="http://maas:8100")
    maas_admin_token: str | None = Field(default=None)
    sandbox_base_url: str = Field(default="http://sandbox:8200")
    jwt_secret: str | None = Field(default=None)
    jwt_access_ttl: int = Field(default=3600)
    jwt_refresh_ttl: int = Field(default=604800)
    enable_auto_code_tools: bool = Field(default=False)
    code_tool_allowlist: str = Field(default="")
    max_request_body_bytes: int = Field(default=2_097_152)
    http_tool_allowed_hosts: str = Field(default="")
    upstream_connect_timeout: float = Field(default=5.0)
    upstream_read_timeout: float = Field(default=60.0)
    upstream_write_timeout: float = Field(default=10.0)
    upstream_pool_timeout: float = Field(default=5.0)
    public_app_rate_limit_per_minute: int = Field(default=60)
    public_app_daily_request_quota: int = Field(default=1000)
    public_app_daily_token_quota: int = Field(default=100_000)
    public_app_daily_cost_quota: float = Field(default=0.0)
    login_failure_limit_per_minute: int = Field(default=5)
    login_rate_limit_fail_open: bool = Field(default=True)
    upload_max_bytes: int = Field(default=20 * 1024 * 1024)
    parser_timeout_seconds: float = Field(default=15.0)
    parser_pdf_max_pages: int = Field(default=200)
    db_pool_size: int = Field(default=5)
    db_max_overflow: int = Field(default=10)
    db_pool_timeout: float = Field(default=30.0)
    db_pool_recycle: int = Field(default=1800)
    computer_use_enabled: bool = Field(default=False)
    computer_use_max_session_minutes: int = Field(default=15)
    computer_use_max_actions: int = Field(default=20)


settings = Settings()
settings.jwt_secret = resolve_runtime_secret(
    env_name="JWT_SECRET",
    file_name="backend_jwt_secret",
    label="Backend JWT_SECRET",
    configured_value=settings.jwt_secret,
)
