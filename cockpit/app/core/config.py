from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "cockpit-service"
    app_version: str = "0.1.0"
    database_url: str = Field(..., alias="DATABASE_URL")
    jwt_signing_key: str = Field(..., alias="JWT_SIGNING_KEY")
    wanwu_bff_base_url: str = Field("http://bff-service:6668", alias="WANWU_BFF_BASE_URL")
    wanwu_bff_timeout_seconds: float = Field(5.0, alias="WANWU_BFF_TIMEOUT_SECONDS")
    wanwu_svc_username: str | None = Field(None, alias="WANWU_SVC_USERNAME")
    wanwu_svc_password: str | None = Field(None, alias="WANWU_SVC_PASSWORD")
    wanwu_svc_token: str | None = Field(None, alias="WANWU_SVC_TOKEN")
    wanwu_svc_captcha_key: str | None = Field(None, alias="WANWU_SVC_CAPTCHA_KEY")
    wanwu_svc_captcha_code: str | None = Field(None, alias="WANWU_SVC_CAPTCHA_CODE")
    eval_timeout_seconds: float = Field(120.0, alias="EVAL_TIMEOUT_SECONDS")
    eval_default_concurrency: int = Field(2, alias="EVAL_DEFAULT_CONCURRENCY")
    experience_embedding_dim: int = Field(1024, alias="EXPERIENCE_EMBEDDING_DIM")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
