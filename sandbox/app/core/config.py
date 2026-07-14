from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Enterprise AI Platform Sandbox"
    app_version: str = "0.1.0"
    service_name: str = "sandbox"
    exec_timeout_seconds: int = 10
    exec_output_limit: int = 12000
    max_concurrency: int = 2
    cpu_seconds: int = 5
    memory_mb: int = 256
    max_open_files: int = 64
    max_processes: int = 32


settings = Settings()
