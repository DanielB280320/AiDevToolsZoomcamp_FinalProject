"""Application settings, read from environment variables (spec §6.4: no secrets in git).

Every setting is documented in `backend/.env.example`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Final, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "dev", "prod"]
# Only for local runs and tests; dev and prod must set USER_HASH_SALT (see model validator).
_LOCAL_USER_HASH_SALT = "fitwise-local-user-hash-salt"
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class DatabaseSettings(BaseSettings):
    """The database connection only. Alembic migrations need nothing else (no JWT secret)."""

    # hide_input_in_errors: a rejected value (a too-short JWT_SECRET or USER_HASH_SALT, a DB URL
    # with a password) is never echoed in the startup ValidationError. Inherited by `Settings`.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", frozen=True, hide_input_in_errors=True
    )

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


class ProcessSettings(DatabaseSettings):
    """What any FitWise process needs: the database plus its environment, log level and release.

    The one-shot migration step (`python -m app.migrate`) uses exactly this: it needs no JWT
    secret or telemetry key (least privilege, spec §11, D50).
    """

    app_env: Environment = Field(default="local", description="Deployment environment name.")
    log_level: LogLevel = Field(default="INFO", description="Root log level of the app.")
    app_version: str = Field(
        default="dev",
        min_length=1,
        max_length=64,
        description="Release version (the image's git SHA); OTel resource `service.version`.",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class Settings(ProcessSettings):
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

    off_base_url: str = Field(
        default="https://world.openfoodfacts.org",
        description="Open Food Facts base URL (env OFF_BASE_URL); tests point it at a fake server.",
    )
    off_contact: str = Field(
        default="https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject",
        min_length=1,
        max_length=200,
        description="Contact in the Open Food Facts User-Agent `FitWise/<version> (<contact>)`.",
    )
    off_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        le=10,
        description=(
            "Total deadline in seconds for one Open Food Facts request, connect to last body "
            "byte (spec F6: 3 s); a slower upstream counts as a timeout."
        ),
    )

    @field_validator("off_base_url")
    @classmethod
    def _strip_off_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

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


@lru_cache
def get_settings() -> Settings:
    """Settings from the process environment, loaded once."""
    return Settings()  # database_url and jwt_secret are required, from the environment


# --------------------------------------------------------------------------------------------
# Feature flags (spec §8 `FeatureFlag`, F6, F11.5, §15.2, §15.3). Not environment settings: they
# live in the `feature_flag` table, are changed at runtime with the ops CLI
# (`python -m app.cli.flags`, wrapped by `oncall/ops/flag.sh`) and read by services through the
# cached `app.services.flags.FlagReader`. Engines never read flags; services pass them in.


@dataclass(frozen=True)
class FlagSpec:
    """An allow-listed flag: its default, and either a closed set of values or an integer range.

    Values are stored as text. A stored value outside the spec (written by hand, or by a newer
    release that knows more values) reads as the default.
    """

    default: str
    choices: tuple[str, ...] = ()
    int_max: int | None = None  # set for non-negative integer flags: 0..int_max inclusive


# Upper bound of the demo latency fault (S3). Above the 1 s KeyJourneyLatency threshold (§15.1),
# below any proxy timeout, so the demo slows requests without failing them.
FAULT_INJECTION_LATENCY_MS_MAX: Final = 10_000
# A flag change is seen by every running backend within this many seconds (cache TTL). The
# on-call runbooks rely on "a flag change takes effect within 10 s"; keep it well below that.
FLAG_CACHE_TTL_SECONDS: Final = 5

FEATURE_FLAGS: Final[Mapping[str, FlagSpec]] = MappingProxyType(
    {
        # F11.5: progression engine version; unknown stored values fall back to v1.
        # v2 is the DEMO-ONLY faulty engine of §15.3 S2 (raises on bodyweight exercises): never
        # set it outside the demo.
        "progression_engine": FlagSpec(default="v1", choices=("v1", "v2")),
        # F6: Open Food Facts search; off -> the search degrades to `available: false` (D44).
        "off_search_enabled": FlagSpec(default="true", choices=("true", "false")),
        # §15.3 S3, demo only, off by default: delay (ms) added to the §15.1 logging routes.
        "fault_injection_latency_ms": FlagSpec(default="0", int_max=FAULT_INJECTION_LATENCY_MS_MAX),
    }
)
