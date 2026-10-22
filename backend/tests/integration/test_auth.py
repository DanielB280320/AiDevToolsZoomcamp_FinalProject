"""`POST /auth/signup`, `/auth/login`, `/auth/logout` against real Postgres (spec F1)."""

import datetime as dt
import re
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import PASSWORD, Api, field_errors, problem, signup_body

SESSION_COOKIE_RE = (
    r"^fitwise_session=[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+; "
    r"HttpOnly; SameSite=Lax; Path=/; Max-Age=86400$"
)
CLEARED_COOKIE = "fitwise_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"


def _db(api: Api) -> Any:
    return create_engine(api.app.state.settings.database_url.get_secret_value())


# ───────────── sign-up ─────────────


def test_signup_returns_201_me_and_session_cookie(api: Api) -> None:
    response = api.signup()

    assert response.status_code == 201, response.text
    me = response.json()
    assert_matches_schema(me, "Me")
    assert me["email"] == "ana@x.test"
    assert me["role"] == "athlete"
    assert me["birth_date"] == "1995-04-12"
    assert me["disclaimer_accepted_at"] == "2026-10-22T09:00:00Z"
    assert me["created_at"] == "2026-10-22T09:00:00Z"
    assert (me["onboarding_completed"], me["active_coach"], me["pending_coach_link_id"]) == (
        False,
        None,
        None,
    )
    assert me["unread_notification_count"] == 0
    assert "password" not in me and "password_hash" not in me
    set_cookie = response.headers.get_list("set-cookie")
    assert len(set_cookie) == 1
    assert re.match(SESSION_COOKIE_RE, set_cookie[0]), set_cookie[0]
    # The new session works straight away.
    assert api.client.get("/api/v1/me").json()["id"] == me["id"]


def test_secure_cookie_attribute_is_a_setting(api_factory: Any) -> None:
    secure = api_factory(session_cookie_secure=True)
    response = secure.signup()
    assert response.status_code == 201
    assert response.headers["set-cookie"].endswith("; Max-Age=86400; Secure")
    logout = secure.client.post("/api/v1/auth/logout")
    assert logout.headers["set-cookie"] == CLEARED_COOKIE + "; Secure"


def test_coach_signup_is_onboarded(api: Api) -> None:
    me = api.signup(email="lucia@x.test", role="coach").json()
    assert_matches_schema(me, "Me")
    assert (me["role"], me["onboarding_completed"]) == ("coach", True)


def test_password_is_stored_as_argon2id_hash(api: Api) -> None:
    api.signup()
    engine = _db(api)
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT password_hash FROM users")).scalar_one()
    engine.dispose()
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


def test_disclaimer_acceptance_time_is_stored_in_utc(api: Api) -> None:
    api.signup()
    engine = _db(api)
    with engine.connect() as connection:
        connection.execute(text("SET TIME ZONE 'America/New_York'"))
        stored = connection.execute(text("SELECT disclaimer_accepted_at FROM users")).scalar_one()
    engine.dispose()
    assert stored == dt.datetime(2026, 10, 22, 9, 0, tzinfo=dt.UTC)


def test_signup_without_disclaimer_is_422_disclaimer_required(api: Api) -> None:
    body = problem(api.signup(accept_disclaimer=False), 422, "disclaimer_required")
    assert ("accept_disclaimer", "disclaimer_required") in field_errors(body)
    assert "set-cookie" not in api.signup(accept_disclaimer=False).headers


@pytest.mark.parametrize(
    ("now", "timezone", "birth_date", "adult"),
    [
        # 23:30 UTC on 21 Oct is already 22 Oct in Auckland (UTC+13) but not in Los Angeles.
        ("2026-10-21T23:30:00Z", "Pacific/Auckland", "2008-10-22", True),
        ("2026-10-21T23:30:00Z", "America/Los_Angeles", "2008-10-22", False),
        # 03:00 UTC on 22 Oct is still 21 Oct in Los Angeles (UTC-7) but 22 Oct in Madrid.
        ("2026-10-22T03:00:00Z", "America/Los_Angeles", "2008-10-22", False),
        ("2026-10-22T03:00:00Z", "Europe/Madrid", "2008-10-22", True),
        ("2026-10-22T03:00:00Z", "America/Los_Angeles", "2008-10-21", True),
        ("2026-10-22T03:00:00Z", "Europe/Madrid", "2008-10-23", False),
    ],
)
def test_signup_age_is_computed_in_the_users_time_zone(
    api: Api, now: str, timezone: str, birth_date: str, adult: bool
) -> None:
    api.clock.set(dt.datetime.fromisoformat(now))
    response = api.signup(timezone=timezone, birth_date=birth_date)
    if adult:
        assert response.status_code == 201, response.text
    else:
        body = problem(response, 422, "underage")
        assert ("birth_date", "underage") in field_errors(body)
        assert "18" in body["detail"]


@pytest.mark.parametrize(
    ("existing", "attempt"),
    [("ana@x.test", "Ana@x.test"), ("Ana@x.test", "ana@X.TEST"), ("ana@x.test", "ana@x.test")],
)
def test_duplicate_email_is_409_case_insensitive(api: Api, existing: str, attempt: str) -> None:
    assert api.signup(email=existing).status_code == 201
    problem(
        api.new_client().post("/api/v1/auth/signup", json=signup_body(email=attempt)),
        409,
        "email_taken",
    )


def test_email_uniqueness_is_a_lower_case_unique_index(api: Api) -> None:
    api.signup(email="ana@x.test")
    engine = _db(api)
    with engine.connect() as connection:
        definition = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_users_lower_email'")
        ).scalar_one()
        with pytest.raises(Exception, match="uq_users_lower_email"):
            connection.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, display_name, role, birth_date,"
                    " units, timezone, disclaimer_accepted_at, created_at, updated_at) VALUES"
                    " (gen_random_uuid(), 'ANA@X.TEST', 'x', 'x', 'athlete', '1990-01-01',"
                    " 'metric', 'UTC', now(), now(), now())"
                )
            )
    engine.dispose()
    assert "UNIQUE INDEX" in definition and "lower((email)::text)" in definition


@pytest.mark.parametrize("password", ["", "a", "123456789", "ninechars"])
def test_short_password_is_422_too_short(api: Api, password: str) -> None:
    body = problem(api.signup(password=password), 422, "validation_error")
    assert ("password", "too_short") in field_errors(body)


def test_ten_character_password_is_accepted(api: Api) -> None:
    assert api.signup(password="0123456789").status_code == 201


@pytest.mark.parametrize("timezone", ["Mars/Olympus_Mons", "europe/madrid", "", "GMT+25"])
def test_invalid_timezone_is_422_on_timezone(api: Api, timezone: str) -> None:
    body = problem(api.signup(timezone=timezone), 422, "validation_error")
    assert "timezone" in {field for field, _ in field_errors(body)}


@pytest.mark.parametrize(
    ("overrides", "field", "code"),
    [
        ({"email": "not-an-email"}, "email", "invalid_format"),
        ({"email": "a" * 250 + "@x.test"}, "email", "too_long"),
        ({"display_name": "   "}, "display_name", "too_short"),
        ({"display_name": "x" * 61}, "display_name", "too_long"),
        ({"role": "admin"}, "role", "invalid_choice"),
        ({"units": "furlongs"}, "units", "invalid_choice"),
        ({"birth_date": "12/04/1995"}, "birth_date", "invalid_format"),
        ({"accept_disclaimer": "yes"}, "accept_disclaimer", "invalid_type"),
        ({"password": "x" * 129}, "password", "too_long"),
        ({"is_admin": True}, "is_admin", "unknown_field"),
    ],
)
def test_signup_schema_violations_are_422(
    api: Api, overrides: dict[str, Any], field: str, code: str
) -> None:
    body = problem(api.signup(**overrides), 422, "validation_error")
    assert (field, code) in field_errors(body)


def test_signup_missing_fields_are_422_required(api: Api) -> None:
    body = problem(api.client.post("/api/v1/auth/signup", json={}), 422, "validation_error")
    assert ("email", "required") in field_errors(body)
    assert ("accept_disclaimer", "required") in field_errors(body)


def test_signup_unparseable_json_is_400(api: Api) -> None:
    response = api.client.post(
        "/api/v1/auth/signup", content=b"{not json", headers={"content-type": "application/json"}
    )
    problem(response, 400, "bad_request")


# ───────────── sign-in ─────────────


def test_login_returns_200_me_and_cookie(api: Api) -> None:
    created = api.signup().json()
    browser = api.new_client()
    response = browser.post(
        "/api/v1/auth/login", json={"email": "ANA@x.test", "password": PASSWORD}
    )

    assert response.status_code == 200, response.text
    assert_matches_schema(response.json(), "Me")
    assert response.json() == created
    assert re.match(SESSION_COOKIE_RE, response.headers["set-cookie"])
    assert browser.get("/api/v1/me").status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_401(api: Api) -> None:
    api.signup()
    wrong_password = api.login(password="wrong-password-123")
    unknown_email = api.login(email="nobody@x.test")

    problem(wrong_password, 401, "invalid_credentials")
    problem(unknown_email, 401, "invalid_credentials")
    # Identical apart from request_id, which is the trace id of each request.
    assert {**wrong_password.json(), "request_id": None} == {
        **unknown_email.json(),
        "request_id": None,
    }
    assert "set-cookie" not in wrong_password.headers
    assert "set-cookie" not in unknown_email.headers


def test_login_schema_violation_is_422(api: Api) -> None:
    body = problem(
        api.client.post("/api/v1/auth/login", json={"email": "ana@x.test"}),
        422,
        "validation_error",
    )
    assert ("password", "required") in field_errors(body)


# ───────────── F1.6 rate limit ─────────────


def _fail(api: Api, times: int, email: str = "ana@x.test") -> None:
    for _ in range(times):
        problem(api.login(email=email, password="wrong-password-123"), 401, "invalid_credentials")


def test_sixth_failed_sign_in_within_15_minutes_is_429(api: Api) -> None:
    api.signup()
    _fail(api, 5)

    body = problem(api.login(password="wrong-password-123"), 429, "rate_limited")
    assert "15 minutes" in body["detail"]


def test_locked_email_gets_429_even_with_the_right_password(api: Api) -> None:
    api.signup()
    _fail(api, 5)
    api.clock.advance(minutes=4)

    response = api.login()
    problem(response, 429, "rate_limited")
    assert response.headers["retry-after"] == str(11 * 60)
    assert "set-cookie" not in response.headers


def test_rate_limit_is_per_email_and_case_insensitive(api: Api) -> None:
    api.signup()
    api.signup(email="ben@x.test")
    for email in ("ana@x.test", "ANA@x.test", "Ana@X.test", "ana@x.TEST", "aNa@x.test"):
        _fail(api, 1, email=email)

    problem(api.login(email="ANA@X.TEST"), 429, "rate_limited")
    assert api.login(email="ben@x.test").status_code == 200  # other emails are unaffected


def test_unknown_emails_are_rate_limited_too(api: Api) -> None:
    _fail(api, 5, email="nobody@x.test")
    problem(api.login(email="nobody@x.test"), 429, "rate_limited")


def test_attempts_after_the_window_are_evaluated_normally(api: Api) -> None:
    api.signup()
    _fail(api, 5)
    api.clock.advance(minutes=14, seconds=59)
    response = api.login()
    problem(response, 429, "rate_limited")
    assert response.headers["retry-after"] == "1"

    api.clock.advance(seconds=1)  # exactly 15 min after the 5 failures
    assert api.login().status_code == 200


def test_window_slides_with_the_oldest_failure(api: Api) -> None:
    api.signup()
    _fail(api, 1)
    api.clock.advance(minutes=10)
    _fail(api, 4)
    problem(api.login(), 429, "rate_limited")

    api.clock.advance(minutes=5)  # the first failure has left the window: 4 remain
    _fail(api, 1)  # evaluated normally (401), back to 5 in the window
    response = api.login()
    problem(response, 429, "rate_limited")
    # The oldest failure still in the window is at T+10 min, so the lock ends at T+25 min.
    assert response.headers["retry-after"] == str(10 * 60)


def test_failures_spread_over_more_than_15_minutes_do_not_lock(api: Api) -> None:
    api.signup()
    for _ in range(10):
        _fail(api, 1)
        api.clock.advance(minutes=4)
    assert api.login().status_code == 200


def test_successful_sign_in_resets_the_failure_count(api: Api) -> None:
    api.signup()
    _fail(api, 4)
    assert api.login().status_code == 200
    _fail(api, 4)
    assert api.login().status_code == 200


def test_rate_limit_does_not_store_the_email(api: Api) -> None:
    _fail(api, 2, email="Secret.Person@x.test")
    engine = _db(api)
    with engine.connect() as connection:
        keys = connection.execute(text("SELECT email_key FROM sign_in_failures")).scalars().all()
    engine.dispose()
    assert len(keys) == 2
    assert all("secret" not in key.lower() and len(key) == 64 for key in keys)


# ───────────── sign-out ─────────────


def test_logout_clears_the_cookie_and_ends_the_session(api: Api) -> None:
    api.signup()
    response = api.client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["set-cookie"] == CLEARED_COOKIE
    problem(api.client.get("/api/v1/me"), 401, "not_authenticated")


def test_logout_without_a_session_is_204(api: Api) -> None:
    response = api.new_client().post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert response.headers["set-cookie"] == CLEARED_COOKIE


def test_logout_with_a_garbage_cookie_is_204(api: Api) -> None:
    browser = api.new_client()
    browser.cookies.set("fitwise_session", "garbage")
    assert browser.post("/api/v1/auth/logout").status_code == 204
