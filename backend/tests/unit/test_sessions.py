import datetime as dt
import uuid

import jwt
import pytest

from app.services.passwords import hash_password, verify_password
from app.services.sessions import (
    SESSION_TTL,
    cleared_session_cookie,
    issue_token,
    read_token,
    session_cookie,
)

SECRET = "unit-test-jwt-secret-0123456789abcdef"
NOW = dt.datetime(2026, 10, 22, 9, 0, tzinfo=dt.UTC)
USER = uuid.UUID("3f0b6a1e-6a55-4f3c-9a43-1c2a3a4b5c6d")


def test_token_round_trip_within_24_hours() -> None:
    token = issue_token(USER, NOW, SECRET)
    assert read_token(token, NOW, SECRET) == USER
    assert read_token(token, NOW + SESSION_TTL - dt.timedelta(seconds=1), SECRET) == USER


def test_token_holds_only_the_user_id_and_times() -> None:
    claims = jwt.decode(
        issue_token(USER, NOW, SECRET),
        SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert set(claims) == {"sub", "iat", "exp"}
    assert claims["exp"] - claims["iat"] == 86400


@pytest.mark.parametrize("offset", [SESSION_TTL, SESSION_TTL + dt.timedelta(seconds=1)])
def test_token_expires_after_24_hours(offset: dt.timedelta) -> None:
    assert read_token(issue_token(USER, NOW, SECRET), NOW + offset, SECRET) is None


def test_token_from_the_future_is_rejected() -> None:
    assert read_token(issue_token(USER, NOW, SECRET), NOW - dt.timedelta(minutes=1), SECRET) is None


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-jwt",
        issue_token(USER, NOW, "another-secret-0123456789abcdef-xyz"),
        jwt.encode({"sub": str(USER), "iat": 0, "exp": 2**40}, SECRET, algorithm="HS256"),  # >24h
        jwt.encode(
            {"sub": "not-a-uuid", "iat": int(NOW.timestamp()), "exp": int(NOW.timestamp()) + 60},
            SECRET,
            algorithm="HS256",
        ),
        jwt.encode({"sub": str(USER), "exp": int(NOW.timestamp()) + 60}, SECRET, algorithm="HS256"),
    ],
)
def test_invalid_tokens_are_rejected(token: str) -> None:
    assert read_token(token, NOW, SECRET) is None


@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
def test_other_algorithms_are_rejected() -> None:
    claims = {"sub": str(USER), "iat": int(NOW.timestamp()), "exp": int(NOW.timestamp()) + 60}
    assert read_token(jwt.encode(claims, SECRET, algorithm="HS512"), NOW, SECRET) is None


def test_tampered_payload_is_rejected() -> None:
    header, payload, signature = issue_token(USER, NOW, SECRET).split(".")
    other = issue_token(uuid.uuid4(), NOW, SECRET).split(".")[1]
    assert read_token(f"{header}.{other}.{signature}", NOW, SECRET) is None
    assert read_token(f"{header}.{payload}.{signature[:-2]}xx", NOW, SECRET) is None


def test_none_algorithm_is_rejected() -> None:
    token = jwt.encode(
        {"sub": str(USER), "iat": int(NOW.timestamp()), "exp": int(NOW.timestamp()) + 60},
        None,
        algorithm="none",
    )
    assert read_token(token, NOW, SECRET) is None


@pytest.mark.parametrize(("secure", "suffix"), [(False, ""), (True, "; Secure")])
def test_cookie_attributes_match_the_contract(secure: bool, suffix: str) -> None:
    assert session_cookie("abc.def.ghi", secure=secure) == (
        "fitwise_session=abc.def.ghi; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400" + suffix
    )
    assert cleared_session_cookie(secure=secure) == (
        "fitwise_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0" + suffix
    )


def test_passwords_are_argon2id_hashes() -> None:
    hashed = hash_password("correct-horse-battery")
    assert hashed.startswith("$argon2id$")
    assert "correct-horse-battery" not in hashed
    assert verify_password(hashed, "correct-horse-battery")
    assert not verify_password(hashed, "correct-horse-batterY")
    assert not verify_password(None, "correct-horse-battery")
    assert not verify_password("not-a-hash", "correct-horse-battery")
