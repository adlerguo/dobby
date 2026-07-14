from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secrets import resolve_runtime_secret


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Enterprise AI Platform MaaS"
    app_version: str = "0.1.0"
    service_name: str = "maas"

    database_url: str = Field(default="postgresql+psycopg://app:pass@postgres:5432/eap")
    redis_url: str = Field(default="redis://redis:6379/0")
    maas_encryption_key: str | None = Field(default=None)
    maas_cache_ttl: int = Field(default=300)
    max_request_body_bytes: int = Field(default=2_097_152)
    production_mode: bool = Field(default=True)


settings = Settings()
settings.maas_encryption_key = resolve_runtime_secret(
    env_name="MAAS_ENCRYPTION_KEY",
    file_name="maas_encryption_key",
    label="MaaS MAAS_ENCRYPTION_KEY",
    configured_value=settings.maas_encryption_key,
)
