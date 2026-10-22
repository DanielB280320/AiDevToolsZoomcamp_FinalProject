"""QA checks for #8 that complement the implementer's tests.

* concurrent failed sign-ins cannot overshoot the F1.6 limit (advisory lock)
* attempts made while locked are not counted, and the window slides one failure at a time
* the 429 for a known and an unknown email look the same (no account-existence oracle)
* SQLAlchemy echo is really captured and never shows bound parameters (hide_parameters)
* `date-time` fields are UTC with a `Z` suffix (the contract format checker does not check
  `date-time` without `rfc3339-validator`, so this is asserted explicitly)
"""

import datetime as dt
import logging
import threading
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import StatementError

from app.dependencies import SessionDep
from app.errors import ProblemError
from app.models import SignInFailure
from app.services import accounts
from tests.integration.auth_helpers import NOW, PASSWORD, Api, problem

EMAIL = "Race.Person@x.test"


def _failure_count(api: Api) -> int:
    with api.app.state.session_factory() as session:
        count: int = session.scalar(select(func.count()).select_from(SignInFailure)) or 0
    return count


def test_concurrent_failed_sign_ins_cannot_overshoot_the_limit(api: Api) -> None:
    assert api.signup(email=EMAIL).status_code == 201
    attempts = 12
    barrier = threading.Barrier(attempts)
    outcomes: list[int] = []
    lock = threading.Lock()

    def attempt() -> None:
        with api.app.state.session_factory() as session:
            barrier.wait()
            try:
                accounts.log_in(session, EMAIL.lower(), "wrong-password-race", NOW)
                status = 200
            except ProblemError as error:
                status = error.status
        with lock:
            outcomes.append(status)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(outcomes) == [401] * 5 + [429] * (attempts - 5)
    assert _failure_count(api) == 5


def test_attempts_while_locked_are_not_counted_and_the_window_slides(api: Api) -> None:
    assert api.signup(email=EMAIL).status_code == 201
    for _ in range(5):  # failures at 0, 1, 2, 3, 4 minutes
        problem(api.login(EMAIL, "wrong-password-1"), 401, "invalid_credentials")
        api.clock.advance(minutes=1)

    # 5 min: locked until the first failure leaves the window at 15 min.
    locked = api.login(EMAIL, PASSWORD)
    problem(locked, 429, "rate_limited")
    assert locked.headers["Retry-After"] == "600"
    api.clock.advance(minutes=5)  # 10 min; more locked attempts must not extend the lockout
    for _ in range(3):
        assert api.login(EMAIL, "wrong-password-2").status_code == 429
    assert api.login(EMAIL, PASSWORD).headers["Retry-After"] == "300"
    assert _failure_count(api) == 5

    api.clock.set(NOW + dt.timedelta(minutes=15))  # first failure left; 4 remain
    problem(api.login(EMAIL, "wrong-password-3"), 401, "invalid_credentials")
    # 5 in the window again; the oldest is now the 1-minute one -> unlock at 16 min.
    assert api.login(EMAIL, PASSWORD).headers["Retry-After"] == "60"

    api.clock.set(NOW + dt.timedelta(minutes=16))
    assert api.login(EMAIL, PASSWORD).status_code == 200
    assert _failure_count(api) == 0


def test_429_does_not_reveal_whether_the_account_exists(api: Api) -> None:
    assert api.signup(email=EMAIL).status_code == 201
    for email in (EMAIL, "nobody.here@x.test"):
        for _ in range(5):
            api.login(email, "wrong-password-1")
    known = api.login(EMAIL, PASSWORD)
    unknown = api.login("nobody.here@x.test", PASSWORD)
    assert known.status_code == unknown.status_code == 429
    # Identical bodies apart from request_id (#16), which is each request's own trace id.
    known_body, unknown_body = known.json(), unknown.json()
    assert len(known_body.pop("request_id")) == len(unknown_body.pop("request_id")) == 32
    assert known_body == unknown_body
    assert known.headers["Retry-After"] == unknown.headers["Retry-After"]
    assert "set-cookie" not in known.headers and "set-cookie" not in unknown.headers


def test_sql_echo_never_shows_bound_parameters(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="sqlalchemy.engine")
    secret_name = "Quentin Hiddenname"
    assert api.signup(email=EMAIL, display_name=secret_name).status_code == 201
    assert api.login(EMAIL, "wrong-password-1").status_code == 401
    assert api.login(EMAIL.upper(), PASSWORD).status_code == 200
    token = api.client.cookies.get("fitwise_session")
    assert token

    sql_records = [r for r in caplog.records if r.name.startswith("sqlalchemy.engine")]
    messages = "\n".join(r.getMessage() for r in sql_records)
    # The check is only meaningful if SQL echo was actually captured.
    assert "INSERT INTO users" in messages
    assert "hide_parameters=True" in messages
    with api.app.state.session_factory() as session:
        password_hash = session.execute(text("SELECT password_hash FROM users")).scalar_one()
    for value in (EMAIL, EMAIL.lower(), EMAIL.upper(), PASSWORD, secret_name, token, password_hash):
        assert value not in messages


_DUPLICATE_INSERT = text(
    "INSERT INTO users (id, email, password_hash, display_name, role, birth_date,"
    " units, timezone, disclaimer_accepted_at, created_at, updated_at) VALUES"
    " (gen_random_uuid(), :email, 'h', 'n', 'athlete', '1990-01-01', 'metric',"
    " 'Etc/UTC', now(), now(), now())"
)


def test_statement_errors_hide_the_bound_parameters(api: Api) -> None:
    """`hide_parameters` hides the bound values. NOTE: the PostgreSQL DETAIL line of a unique
    violation still quotes the key (`Key (lower((email)::text))=(...) already exists`), so such
    exceptions must never be logged or chained with their message (QA finding on #8)."""
    assert api.signup(email=EMAIL).status_code == 201
    with api.app.state.session_factory() as session, pytest.raises(StatementError) as raised:
        session.execute(_DUPLICATE_INSERT, {"email": EMAIL.upper()})
    rendered = str(raised.value)
    assert "[SQL parameters hidden due to hide_parameters=True]" in rendered
    assert EMAIL.upper() not in rendered


def test_an_uncaught_database_error_quoting_the_email_stays_out_of_logs_and_body(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    """The 500 safety net is the last line of defence for driver messages that quote values."""
    caplog.set_level(logging.DEBUG)
    assert api.signup(email=EMAIL).status_code == 201
    router = APIRouter(prefix="/api/v1/_qa")

    @router.post("/duplicate-user")
    def duplicate_user(session: SessionDep) -> None:
        session.execute(_DUPLICATE_INSERT, {"email": EMAIL.upper()})

    api.app.include_router(router)
    client = TestClient(api.app, raise_server_exceptions=False)
    response = client.post("/api/v1/_qa/duplicate-user")

    problem(response, 500, "internal_error")
    logged = "\n".join(
        [r.getMessage() for r in caplog.records] + [str(r.__dict__) for r in caplog.records]
    ).lower()
    assert EMAIL.lower() not in response.text.lower()
    assert EMAIL.lower() not in logged


@pytest.mark.parametrize("operation", ["signup", "login", "me", "patch"])
def test_date_times_are_utc_with_z(api: Api, operation: str) -> None:
    signup = api.signup(email=EMAIL)
    responses: dict[str, Any] = {
        "signup": lambda: signup,
        "login": lambda: api.login(EMAIL, PASSWORD),
        "me": lambda: api.client.get("/api/v1/me"),
        "patch": lambda: api.client.patch("/api/v1/me", json={"timezone": "Asia/Tokyo"}),
    }
    body = responses[operation]().json()
    for field in ("disclaimer_accepted_at", "created_at"):
        assert body[field].endswith("Z"), body[field]
        parsed = dt.datetime.fromisoformat(body[field])
        assert parsed.utcoffset() == dt.timedelta(0)
    assert body["disclaimer_accepted_at"] == "2026-10-22T09:00:00Z"
