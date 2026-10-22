"""`current_user` binds the signed-in user to the request's telemetry as `user_hash` (spec §6.5)."""

import uuid

from fastapi.testclient import TestClient

from app.main import create_app
from app.telemetry.privacy import user_hash
from tests.conftest import Captured, JsonLogs, captured_telemetry, make_settings
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, signup_body


def _captured_app(database_url: str) -> Captured:
    settings = make_settings(database_url)
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    return Captured(app, telemetry, span_exporter, metric_reader)


def test_authenticated_requests_carry_user_hash_and_never_the_raw_id(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    captured = _captured_app(migrated_database_url)
    with TestClient(captured.app) as client:
        user_id = client.post("/api/v1/auth/signup", json=signup_body()).json()["id"]
        assert client.get("/api/v1/me").status_code == 200
        assert client.patch("/api/v1/me", json={"units": "imperial"}).status_code == 200

    expected = user_hash(uuid.UUID(user_id), captured.app.state.settings.user_hash_salt_bytes)
    access = {line["route"]: line for line in json_logs.with_message("request")}
    assert access["/api/v1/me"]["user_hash"] == expected
    server_spans = [s for s in captured.server_spans() if (s.attributes or {}).get("user_hash")]
    assert len(server_spans) == 2  # GET and PATCH /me
    assert all((s.attributes or {})["user_hash"] == expected for s in server_spans)
    assert user_id not in json_logs.text
    for span in captured.spans():
        assert user_id not in str(span.to_json())


def test_unauthenticated_requests_have_no_user_hash(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    captured = _captured_app(migrated_database_url)
    with TestClient(captured.app) as client:
        assert client.get("/api/v1/me").status_code == 401

    [access] = json_logs.with_message("request")
    assert access["status"] == 401
    assert "user_hash" not in access
