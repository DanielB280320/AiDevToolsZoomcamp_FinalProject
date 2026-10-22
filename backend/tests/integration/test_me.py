"""`GET /me`, `PATCH /me`, `current_user` (401) and `require_role` (403) against real Postgres."""

import uuid
from typing import Annotated, Any

import jwt
import pytest
from fastapi import APIRouter, Depends
from sqlalchemy import create_engine, text

from app.dependencies import CurrentUser, require_role
from app.models import User
from app.services.sessions import issue_token
from tests.conftest import TEST_JWT_SECRET
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, field_errors, problem, signup_body

# ───────────── GET /me and 401 ─────────────


def test_get_me_returns_the_signed_in_user(api: Api) -> None:
    created = api.signup().json()
    response = api.client.get("/api/v1/me")

    assert response.status_code == 200
    assert_matches_schema(response.json(), "Me")
    assert response.json() == created


def test_get_me_without_cookie_is_401(api: Api) -> None:
    problem(api.new_client().get("/api/v1/me"), 401, "not_authenticated")


def test_get_me_with_a_tampered_jwt_is_401(api: Api) -> None:
    api.signup()
    token = api.client.cookies["fitwise_session"]
    header, _, signature = token.split(".")
    forged_claims = {"sub": "00000000-0000-4000-8000-000000000000", "iat": 0, "exp": 2**31}
    forged_payload = jwt.encode(forged_claims, "x" * 32, algorithm="HS256").split(".")[1]

    for bad in (
        f"{header}.{forged_payload}.{signature}",
        token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb"),
        jwt.encode(forged_claims, "attacker-chosen-secret-0123456789ab", algorithm="HS256"),
        "garbage",
    ):
        browser = api.new_client()
        browser.cookies.set("fitwise_session", bad)
        problem(browser.get("/api/v1/me"), 401, "not_authenticated")


def test_get_me_with_an_expired_jwt_is_401(api: Api) -> None:
    api.signup()
    api.clock.advance(hours=23, minutes=59, seconds=59)
    assert api.client.get("/api/v1/me").status_code == 200

    api.clock.advance(seconds=1)  # 24 h after sign-in
    problem(api.client.get("/api/v1/me"), 401, "not_authenticated")
    api.clock.advance(hours=1)
    problem(api.client.get("/api/v1/me"), 401, "not_authenticated")


def test_session_for_a_user_that_no_longer_exists_is_401(api: Api) -> None:
    api.signup()
    engine = create_engine(api.app.state.settings.database_url.get_secret_value())
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users"))
    engine.dispose()
    problem(api.client.get("/api/v1/me"), 401, "not_authenticated")


def test_each_session_sees_only_its_own_account(api: Api) -> None:
    """The cookie identifies the user; there is no way to address someone else's /me."""
    ana = api.signup().json()
    ben_client = api.new_client()
    ben = ben_client.post(
        "/api/v1/auth/signup",
        json=signup_body(email="ben@x.test", display_name="Ben"),
    ).json()
    assert api.client.get("/api/v1/me").json()["id"] == ana["id"]
    assert ben_client.get("/api/v1/me").json()["id"] == ben["id"]


# ───────────── PATCH /me ─────────────


@pytest.mark.parametrize(
    "changes",
    [
        {"display_name": "Ana María"},
        {"units": "imperial"},
        {"timezone": "America/Argentina/Buenos_Aires"},
        {"display_name": "Ana", "units": "imperial", "timezone": "UTC"},
    ],
)
def test_patch_me_updates_only_the_given_fields(api: Api, changes: dict[str, str]) -> None:
    before = api.signup().json()
    response = api.client.patch("/api/v1/me", json=changes)

    assert response.status_code == 200, response.text
    after = response.json()
    assert_matches_schema(after, "Me")
    assert after == {**before, **changes}
    assert api.client.get("/api/v1/me").json() == after  # persisted


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({}, "body", "required"),
        ({"email": "new@x.test"}, "email", "unknown_field"),
        ({"role": "coach"}, "role", "unknown_field"),
        ({"birth_date": "1990-01-01"}, "birth_date", "unknown_field"),
        ({"display_name": ""}, "display_name", "too_short"),
        ({"display_name": None}, "display_name", "invalid_type"),
        ({"units": "stones"}, "units", "invalid_choice"),
        ({"timezone": "Nowhere/Land"}, "timezone", "invalid_choice"),
    ],
)
def test_patch_me_rejects_invalid_bodies_with_422(
    api: Api, body: dict[str, Any], field: str, code: str
) -> None:
    before = api.signup().json()
    result = problem(api.client.patch("/api/v1/me", json=body), 422, "validation_error")
    assert (field, code) in field_errors(result)
    assert api.client.get("/api/v1/me").json() == before  # nothing changed


def test_patch_me_without_session_is_401(api: Api) -> None:
    problem(
        api.new_client().patch("/api/v1/me", json={"units": "imperial"}), 401, "not_authenticated"
    )


def test_patch_me_changes_only_the_callers_account(api: Api) -> None:
    api.signup()
    stranger = api.new_client()
    ben = stranger.post("/api/v1/auth/signup", json=signup_body(email="ben@x.test")).json()

    stranger.patch("/api/v1/me", json={"display_name": "Benji"})

    assert api.client.get("/api/v1/me").json()["display_name"] == "Ana"
    assert stranger.get("/api/v1/me").json()["display_name"] == "Benji"
    assert stranger.get("/api/v1/me").json()["id"] == ben["id"]


# ───────────── require_role (403) ─────────────


def _install_role_routes(api: Api) -> None:
    router = APIRouter(prefix="/api/v1/_test")

    @router.get("/coach-only")
    def coach_only(user: Annotated[User, Depends(require_role("coach"))]) -> dict[str, str]:
        return {"role": user.role}

    @router.get("/athlete-only")
    def athlete_only(user: Annotated[User, Depends(require_role("athlete"))]) -> dict[str, str]:
        return {"role": user.role}

    @router.get("/anyone")
    def anyone(user: CurrentUser) -> dict[str, str]:
        return {"role": user.role}

    api.app.include_router(router)


def test_require_role_allows_the_right_role_and_403s_the_other(api: Api) -> None:
    _install_role_routes(api)
    athlete = api.client
    athlete.post("/api/v1/auth/signup", json=signup_body(email="ana@x.test"))
    coach = api.new_client()
    coach.post("/api/v1/auth/signup", json=signup_body(email="lucia@x.test", role="coach"))

    assert athlete.get("/api/v1/_test/athlete-only").json() == {"role": "athlete"}
    assert coach.get("/api/v1/_test/coach-only").json() == {"role": "coach"}
    problem(athlete.get("/api/v1/_test/coach-only"), 403, "wrong_role")
    problem(coach.get("/api/v1/_test/athlete-only"), 403, "wrong_role")
    assert athlete.get("/api/v1/_test/anyone").status_code == 200
    assert coach.get("/api/v1/_test/anyone").status_code == 200


def test_require_role_without_session_is_401_not_403(api: Api) -> None:
    _install_role_routes(api)
    stranger = api.new_client()
    problem(stranger.get("/api/v1/_test/coach-only"), 401, "not_authenticated")
    problem(stranger.get("/api/v1/_test/athlete-only"), 401, "not_authenticated")


def test_validly_signed_token_for_an_unknown_user_id_is_401(api: Api) -> None:
    browser = api.new_client()
    token = issue_token(uuid.uuid4(), api.clock.now(), TEST_JWT_SECRET)
    browser.cookies.set("fitwise_session", token)
    problem(browser.get("/api/v1/me"), 401, "not_authenticated")
