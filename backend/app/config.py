"""Application settings, read from environment variables (spec §6.4: no secrets in git).

Every setting is documented in `backend/.env.example`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "dev", "prod"]
# Only for local runs and tests; dev and prod must set USER_HASH_SALT (see model validator).
_LOCAL_USER_HASH_SALT = "fitwise-local-user-hash-salt"
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class DatabaseSettings(BaseSettings):
    """The database connection only. Alembic migrations need nothing else (no JWT secret)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    # Secrets are `SecretStr`: they print as `**********` in reprs, logs and tracebacks.
    database_url: SecretStr = Field(
        description="SQLAlchemy URL of the PostgreSQL database (env DATABASE_URL).",
    )
    database_connect_timeout_seconds: int = Field(
        default=3,
        ge=1,
        le=60,
        description="Connect timeout for new DB connections, bounds /readyz latency.",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: object) -> object:
        """Accept plain `postgresql://` / `postgres://` URLs and select the psycopg 3 driver."""
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            for prefix in ("postgresql://", "postgres://"):
                if value.startswith(prefix):
                    return "postgresql+psycopg://" + value.removeprefix(prefix)
        return value


class Settings(DatabaseSettings):
    app_env: Environment = Field(default="local", description="Deployment environment name.")
    log_level: LogLevel = Field(default="INFO", description="Root log level of the app.")
    app_version: str = Field(
        default="dev",
        min_length=1,
        max_length=64,
        description="Release version (the image's git SHA); OTel resource `service.version`.",
    )
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        description="OTLP/HTTP base URL of the collector, e.g. http://otel-collector:4318. "
        "Unset: telemetry is not exported and no network call is made.",
    )
    user_hash_salt: SecretStr | None = Field(
        default=None,
        description="HMAC key for `user_hash` in telemetry. Required in dev and prod.",
    )

    @property
    def user_hash_salt_bytes(self) -> bytes:
        if self.user_hash_salt is not None:
            return self.user_hash_salt.get_secret_value().encode()
        return _LOCAL_USER_HASH_SALT.encode()

    jwt_secret: SecretStr = Field(
        min_length=32,
        description="HMAC key that signs session JWTs (env JWT_SECRET), at least 32 characters.",
    )
    session_cookie_secure: bool = Field(
        default=False,
        description="Add `Secure` to the session cookie; turn on once HTTPS exists (spec §6.4).",
    )

    @property
    def serves_api_docs(self) -> bool:
        """Swagger UI and `/openapi.json` are served everywhere except prod."""
        return self.app_env != "prod"

    @field_validator("otel_exporter_otlp_endpoint")
    @classmethod
    def _strip_endpoint(cls, value: str | None) -> str | None:
        """Empty means unset; a trailing slash is dropped (signal paths are appended)."""
        value = (value or "").strip().rstrip("/")
        return value or None

    @model_validator(mode="after")
    def _deployed_envs_need_a_user_hash_salt(self) -> "Settings":
        salt = self.user_hash_salt.get_secret_value() if self.user_hash_salt else ""
        if self.app_env in ("dev", "prod") and len(salt) < 16:
            raise ValueError(
                "user_hash_salt (USER_HASH_SALT) of >= 16 chars is required in dev/prod"
            )
        return self

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    """Settings from the process environment, loaded once."""
    return Settings()  # database_url and jwt_secret are required, from the environment
