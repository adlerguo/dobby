from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Enterprise AI Platform Sandbox"
    app_version: str = "0.1.0"
    service_name: str = "sandbox"
    exec_timeout_seconds: int = 10
    exec_output_limit: int = 12000


settings = Settings()
