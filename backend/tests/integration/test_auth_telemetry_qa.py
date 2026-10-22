"""QA checks for #8 on top of #16 telemetry (re-verification after the rebase).

* every way of failing authentication (no cookie, garbage, wrong key, a validly signed token
  for a user that does not exist) leaves both the access log line and the server span without
  `user_hash`
* a whole account journey never puts the email, display name, password, raw user id or the
  session token into log lines or into any exported span
* the 429 for a known and an unknown email differ only in `request_id` (a 32-hex trace id) and
  `Date`, in headers as well as body
"""

import datetime as dt
import re
import uuid

import jwt
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.sessions import SESSION_COOKIE, issue_token
from tests.conftest import TEST_JWT_SECRET, Captured, JsonLogs, captured_telemetry, make_settings
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, PASSWORD, Api, signup_body

EMAIL = "Telemetry.Person@x.test"
NAME = "Zebulon Telemetryname"
HEX32 = re.compile(r"[0-9a-f]{32}")


def _captured_app(database_url: str) -> Captured:
    settings = make_settings(database_url)
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    return Captured(app, telemetry, span_exporter, metric_reader)


def test_every_failed_authentication_has_no_user_hash_in_logs_or_spans(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    captured = _captured_app(migrated_database_url)
    ghost = issue_token(uuid.uuid4(), NOW, TEST_JWT_SECRET)  # valid signature, no such user
    wrong_key = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": int(NOW.timestamp()), "exp": int(NOW.timestamp()) + 60},
        "a-completely-different-key-0123456789",
        algorithm="HS256",
    )
    cookies = [None, "garbage", wrong_key, ghost]
    with TestClient(captured.app) as client:
        assert client.post("/api/v1/auth/signup", json=signup_body(email=EMAIL)).status_code == 201
        client.cookies.clear()
        for cookie in cookies:
            if cookie is None:
                client.cookies.clear()
            else:
                client.cookies.set(SESSION_COOKIE, cookie)
            assert client.get("/api/v1/me").status_code == 401

    me_lines = [line for line in json_logs.with_message("request") if line["route"] == "/api/v1/me"]
    assert [line["status"] for line in me_lines] == [401] * len(cookies)
    assert all("user_hash" not in line for line in me_lines)
    me_spans = [
        s
        for s in captured.server_spans()
        if (s.attributes or {}).get("http.route") == "/api/v1/me" or "/me" in s.name
    ]
    assert len(me_spans) == len(cookies)
    assert all("user_hash" not in (s.attributes or {}) for s in me_spans)


def test_an_account_journey_leaks_no_account_data_into_logs_or_spans(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    captured = _captured_app(migrated_database_url)
    with TestClient(captured.app) as client:
        signup = client.post(
            "/api/v1/auth/signup", json=signup_body(email=EMAIL, display_name=NAME)
        )
        user_id = signup.json()["id"]
        token = client.cookies[SESSION_COOKIE]
        assert client.get("/api/v1/me").status_code == 200
        assert client.patch("/api/v1/me", json={"display_name": NAME + " II"}).status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 204
        login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        assert login.status_code == 200
        bad = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "nope-nope-1"})
        assert bad.status_code == 401

    exported = json_logs.text + "\n".join(span.to_json() for span in captured.spans())
    for needle in (
        EMAIL,
        EMAIL.lower(),
        "Zebulon",
        "Telemetryname",
        PASSWORD,
        "nope-nope-1",
        user_id,
        user_id.replace("-", ""),
        token,
        token.split(".")[1],
    ):
        assert needle not in exported, needle
    assert "eyJ" not in exported


def test_429_for_known_and_unknown_email_differ_only_in_request_id_and_date(api: Api) -> None:
    known_email, unknown_email = "Known.Person@x.test", "nobody.here@x.test"
    assert api.signup(email=known_email).status_code == 201
    api.client.cookies.clear()
    for email in (known_email, unknown_email):
        for _ in range(5):
            assert api.login(email, "wrong-password-1").status_code == 401
    api.clock.set(NOW + dt.timedelta(minutes=1))
    known = api.login(known_email, PASSWORD)
    unknown = api.login(unknown_email, PASSWORD)

    assert known.status_code == unknown.status_code == 429
    known_body, unknown_body = known.json(), unknown.json()
    known_id, unknown_id = known_body.pop("request_id"), unknown_body.pop("request_id")
    assert HEX32.fullmatch(known_id) and HEX32.fullmatch(unknown_id) and known_id != unknown_id
    assert known_body == unknown_body
    assert len(known.content) == len(unknown.content)
    ignored = {"date"}
    assert {k: v for k, v in known.headers.items() if k not in ignored} == {
        k: v for k, v in unknown.headers.items() if k not in ignored
    }
