import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_come_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/fitwise")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("USER_HASH_SALT", "a-long-random-test-salt")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/fitwise"
    assert settings.app_env == "prod"
    assert settings.log_level == "WARNING"
    assert settings.database_connect_timeout_seconds == 5


def test_defaults_for_optional_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "LOG_LEVEL", "DATABASE_CONNECT_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(database_url="postgresql+psycopg://db/fitwise", _env_file=None)

    assert (settings.app_env, settings.log_level, settings.database_connect_timeout_seconds) == (
        "local",
        "INFO",
        3,
    )


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgres://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
    ],
)
def test_database_url_uses_the_psycopg_driver(given: str, expected: str) -> None:
    assert Settings(database_url=given, _env_file=None).database_url == expected


@pytest.mark.parametrize("field", ["app_env", "log_level"])
def test_invalid_choices_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings.model_validate({"database_url": "postgresql://h/d", field: "nonsense"})
