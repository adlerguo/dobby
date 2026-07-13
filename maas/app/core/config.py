from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Enterprise AI Platform MaaS"
    app_version: str = "0.1.0"
    service_name: str = "maas"

    database_url: str = Field(default="postgresql+psycopg://app:pass@postgres:5432/eap")
    redis_url: str = Field(default="redis://redis:6379/0")
    maas_encryption_key: str = Field(default="change-me-32-byte-key")
    maas_cache_ttl: int = Field(default=300)


settings = Settings()
