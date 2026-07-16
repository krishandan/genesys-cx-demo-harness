"""Application settings. 12-factor: every knob is an env var, no host assumptions."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    app_version: str = "0.1.0"

    api_key: str = "dev-local-key-change-me"
    default_tenant: str = "northwind"

    database_url: str = "postgresql+psycopg://backlot:backlot@db:5432/backlot"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
