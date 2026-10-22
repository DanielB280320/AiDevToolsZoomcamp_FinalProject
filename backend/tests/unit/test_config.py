from typing import Any

import pytest
from pydantic import ValidationError

from app.config import DatabaseSettings, Settings

JWT_SECRET = "unit-test-jwt-secret-0123456789abcdef"


def _settings(**values: Any) -> Settings:
    """Plain strings in, like environment variables (pydantic turns them into `SecretStr`)."""
    return Settings(**values)


def test_settings_come_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/fitwise")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("USER_HASH_SALT", "a-long-random-test-salt")
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")

    settings = _settings(_env_file=None)

    assert settings.database_url.get_secret_value() == "postgresql+psycopg://u:p@db:5432/fitwise"
    assert settings.jwt_secret.get_secret_value() == JWT_SECRET
    assert settings.session_cookie_secure is True
    assert settings.app_env == "prod"
    assert settings.log_level == "WARNING"
    assert settings.database_connect_timeout_seconds == 5


def test_defaults_for_optional_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_ENV",
        "LOG_LEVEL",
        "DATABASE_CONNECT_TIMEOUT_SECONDS",
        "SESSION_COOKIE_SECURE",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = _settings(
        database_url="postgresql+psycopg://db/fitwise", jwt_secret=JWT_SECRET, _env_file=None
    )

    assert (
        settings.app_env,
        settings.log_level,
        settings.database_connect_timeout_seconds,
        settings.session_cookie_secure,
    ) == ("local", "INFO", 3, False)


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        _settings(jwt_secret=JWT_SECRET, _env_file=None)


def test_jwt_secret_is_required_and_at_least_32_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError, match="jwt_secret"):
        _settings(database_url="postgresql://h/d", _env_file=None)
    with pytest.raises(ValidationError, match="jwt_secret"):
        _settings(database_url="postgresql://h/d", jwt_secret="too-short", _env_file=None)


def test_migrations_need_only_the_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/d")
    assert DatabaseSettings(_env_file=None).database_url.get_secret_value() == (
        "postgresql+psycopg://u:p@h/d"
    )


def test_secrets_never_appear_in_reprs_or_dumps() -> None:
    settings = _settings(
        database_url="postgresql://fitwise:db-password-123@h/d",
        jwt_secret=JWT_SECRET,
        _env_file=None,
    )
    rendered = [
        repr(settings),
        str(settings),
        str(settings.model_dump()),
        settings.model_dump_json(),
    ]
    for text in rendered:
        assert "db-password-123" not in text
        assert JWT_SECRET not in text


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgres://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
    ],
)
def test_database_url_uses_the_psycopg_driver(given: str, expected: str) -> None:
    settings = _settings(database_url=given, jwt_secret=JWT_SECRET, _env_file=None)
    assert settings.database_url.get_secret_value() == expected


@pytest.mark.parametrize("field", ["app_env", "log_level"])
def test_invalid_choices_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings.model_validate(
            {"database_url": "postgresql://h/d", "jwt_secret": JWT_SECRET, field: "nonsense"}
        )


@pytest.mark.parametrize(
    ("values", "secret"),
    [
        ({"jwt_secret": "short-jwt-secret-XYZ"}, "short-jwt-secret-XYZ"),
        # Model-level check: the whole input dict is the error input. JWT_SECRET comes from the
        # environment so the salt is last in it, where an unhidden (truncated) repr shows it.
        ({"app_env": "prod", "user_hash_salt": "salt-XYZ"}, "salt-XYZ"),
    ],
)
def test_startup_errors_never_echo_the_rejected_values(
    values: dict[str, Any], secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hide_input_in_errors: the message printed when startup fails names the field but never
    echoes the rejected value. (`errors()` keeps `input` by design; nothing logs it.)"""
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    with pytest.raises(ValidationError) as excinfo:
        _settings(database_url="postgresql://fitwise:db-password-XYZ@h/d", _env_file=None, **values)
    rendered = f"{excinfo.value}\n{excinfo.value!r}"
    assert secret not in rendered
    assert "XYZ" not in rendered
