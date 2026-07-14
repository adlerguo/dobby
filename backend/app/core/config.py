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
    sandbox_base_url: str = Field(default="http://sandbox:8200")
    jwt_secret: str | None = Field(default=None)
    jwt_access_ttl: int = Field(default=3600)
    jwt_refresh_ttl: int = Field(default=604800)
    enable_auto_code_tools: bool = Field(default=False)
    code_tool_allowlist: str = Field(default="")
    max_request_body_bytes: int = Field(default=2_097_152)
    http_tool_allowed_hosts: str = Field(default="")


settings = Settings()
settings.jwt_secret = resolve_runtime_secret(
    env_name="JWT_SECRET",
    file_name="backend_jwt_secret",
    label="Backend JWT_SECRET",
    configured_value=settings.jwt_secret,
)
