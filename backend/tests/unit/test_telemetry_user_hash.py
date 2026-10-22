"""`user_hash`: keyed pseudonym of the user id (issue #16, spec §6.5)."""

import hashlib
import hmac
import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.config import Settings
from app.telemetry import build_telemetry
from app.telemetry.privacy import user_hash

SALT = b"a-long-random-test-salt"


def test_is_hmac_sha256_of_the_user_id_keyed_with_the_salt() -> None:
    user_id = uuid.UUID("0d9e8f7a-6b5c-4d3e-8f2a-1b0c9d8e7f6a")

    expected = hmac.new(SALT, str(user_id).encode(), hashlib.sha256).hexdigest()[:16]
    assert user_hash(user_id, SALT) == expected
    assert user_hash(str(user_id), SALT) == expected


@given(user_id=st.uuids())
def test_property_same_user_same_hash_and_the_raw_id_never_appears(user_id: uuid.UUID) -> None:
    first = user_hash(user_id, SALT)

    assert first == user_hash(user_id, SALT)
    assert len(first) == 16
    assert int(first, 16) >= 0
    assert str(user_id) not in first
    assert user_id.hex not in first
    # Not an unkeyed hash of the id: without the salt it cannot be recomputed.
    assert first != hashlib.sha256(str(user_id).encode()).hexdigest()[:16]


@given(a=st.uuids(), b=st.uuids())
def test_property_different_users_get_different_hashes(a: uuid.UUID, b: uuid.UUID) -> None:
    if a != b:
        assert user_hash(a, SALT) != user_hash(b, SALT)


def test_a_different_salt_gives_a_different_hash() -> None:
    user_id = uuid.uuid4()

    assert user_hash(user_id, SALT) != user_hash(user_id, b"another-long-random-salt")


def test_the_salt_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://h/d")
    monkeypatch.setenv("USER_HASH_SALT", SALT.decode())
    settings = Settings(_env_file=None)
    user_id = uuid.uuid4()

    assert build_telemetry(settings).hash_user(user_id) == user_hash(user_id, SALT)
    assert SALT.decode() not in repr(settings)  # SecretStr: never printed


@pytest.mark.parametrize("env", ["dev", "prod"])
@pytest.mark.parametrize("salt", [None, "", "too-short"])
def test_dev_and_prod_refuse_to_start_without_a_real_salt(env: str, salt: str | None) -> None:
    with pytest.raises(ValidationError, match="USER_HASH_SALT"):
        Settings.model_validate(
            {"database_url": "postgresql://h/d", "app_env": env, "user_hash_salt": salt}
        )


@pytest.mark.parametrize("env", ["local", "test"])
def test_local_and_test_use_a_fixed_development_salt(env: str) -> None:
    settings = Settings.model_validate({"database_url": "postgresql://h/d", "app_env": env})

    assert settings.user_hash_salt is None
    assert settings.user_hash_salt_bytes
