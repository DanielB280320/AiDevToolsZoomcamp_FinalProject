"""Application settings, read from environment variables (spec §6.4: no secrets in git).

Every setting is documented in `backend/.env.example`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "dev", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    database_url: str = Field(
        description="SQLAlchemy URL of the PostgreSQL database (env DATABASE_URL).",
    )
    database_connect_timeout_seconds: int = Field(
        default=3,
        ge=1,
        le=60,
        description="Connect timeout for new DB connections, bounds /readyz latency.",
    )
    app_env: Environment = Field(default="local", description="Deployment environment name.")
    log_level: LogLevel = Field(default="INFO", description="Root log level of the app.")

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        """Accept plain `postgresql://` / `postgres://` URLs and select the psycopg 3 driver."""
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value.removeprefix(prefix)
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    """Settings from the process environment, loaded once."""
    return Settings()  # database_url is required and comes from the environment
