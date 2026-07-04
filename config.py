"""Shared configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///data/gpuindex.db"
    collector_interval_minutes: int = 60
    collector_timeout_seconds: int = 300
    log_level: str = "INFO"
    contact_email: str = "ops@example.com"

    runpod_api_key: str | None = None
    lambda_api_key: str | None = None

    api_rate_limit_per_minute: int = 60
    site_title: str = "GPU Index"


settings = Settings()
