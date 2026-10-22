"""Rule 6 / spec §6.5: account data never reaches logs or exception messages."""

import logging
import traceback
from typing import Any

import pytest

from app.services import accounts
from tests.integration.auth_helpers import Api, problem, signup_body

EMAIL = "Secret.Person@x.test"
PASSWORD = "hunter2-very-secret-pw"
WRONG_PASSWORD = "wrong-secret-guess-77"
DISPLAY_NAME = "Zebulon Privatename"


def _sensitive(api: Api) -> list[str]:
    values = [EMAIL, EMAIL.lower(), PASSWORD, WRONG_PASSWORD, DISPLAY_NAME, "Renamed Privatename"]
    token = api.client.cookies.get("fitwise_session")
    return [*values, *([token] if token else [])]


def _exercise_every_operation(api: Api) -> list[Any]:
    body = signup_body(email=EMAIL, password=PASSWORD, display_name=DISPLAY_NAME)
    responses = [api.client.post("/api/v1/auth/signup", json=body)]
    responses.append(api.client.post("/api/v1/auth/signup", json=body))  # 409
    responses.append(api.client.post("/api/v1/auth/signup", json={**body, "password": "short"}))
    responses.append(api.client.post("/api/v1/auth/signup", json={**body, "email": "x@"}))
    responses.append(api.client.get("/api/v1/me"))
    responses.append(api.client.patch("/api/v1/me", json={"display_name": "Renamed Privatename"}))
    responses.append(api.client.patch("/api/v1/me", json={"email": EMAIL}))
    for _ in range(6):  # 5 x 401, then 429
        responses.append(api.login(email=EMAIL, password=WRONG_PASSWORD))
    api.clock.advance(minutes=16)
    responses.append(api.login(email=EMAIL, password=PASSWORD))
    responses.append(api.client.post("/api/v1/auth/logout"))
    return responses


def test_no_log_line_contains_account_data(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)  # everything, from every logger (app, sqlalchemy, uvicorn)
    responses = _exercise_every_operation(api)
    sensitive = _sensitive(api)

    assert [r.status_code for r in responses] == [
        201,
        409,
        422,
        422,
        200,
        200,
        422,
        401,
        401,
        401,
        401,
        401,
        429,
        200,
        204,
    ]
    logged = "\n".join(
        [record.getMessage() for record in caplog.records]
        + [str(record.__dict__) for record in caplog.records]
    )
    for value in sensitive:
        assert value not in logged


def test_error_bodies_never_echo_account_data(api: Api) -> None:
    responses = _exercise_every_operation(api)
    for response in responses:
        if response.status_code >= 400:
            for value in (EMAIL, EMAIL.lower(), PASSWORD, WRONG_PASSWORD, DISPLAY_NAME):
                assert value not in response.text


def test_duplicate_email_race_hides_the_database_message(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """If the pre-check misses a concurrent sign-up, the unique index answers 409. The driver
    error (which quotes the email) is neither logged nor chained into the raised exception."""
    caplog.set_level(logging.DEBUG)
    api.client.post("/api/v1/auth/signup", json=signup_body(email=EMAIL))
    monkeypatch.setattr(accounts, "_find_by_email", lambda *_: None)

    raised: list[BaseException] = []
    original = accounts.sign_up

    def spy(*args: Any, **kwargs: Any) -> Any:
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            raised.append(exc)
            raise

    monkeypatch.setattr(accounts, "sign_up", spy)
    response = api.new_client().post("/api/v1/auth/signup", json=signup_body(email=EMAIL.upper()))

    problem(response, 409, "email_taken")
    assert len(raised) == 1
    rendered = "".join(traceback.format_exception(raised[0]))
    assert EMAIL.lower() not in rendered.lower()
    assert all(EMAIL.lower() not in record.getMessage().lower() for record in caplog.records)
