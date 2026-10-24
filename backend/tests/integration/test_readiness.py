import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app
from tests.conftest import make_settings, unreachable_database_url
from tests.contract import assert_matches_schema


def _get_readyz(database_url: str) -> tuple[int, object]:
    with TestClient(create_app(make_settings(database_url))) as client:
        response = client.get("/api/v1/readyz")
    assert response.headers["content-type"] == "application/json"
    assert_matches_schema(response.json(), "Readiness")
    return response.status_code, response.json()


def test_readyz_ok_when_database_reachable_and_migrated(migrated_database_url: str) -> None:
    assert _get_readyz(migrated_database_url) == (
        200,
        {"status": "ok", "checks": {"database": "ok", "migrations": "ok"}},
    )


def test_readyz_503_pending_when_migrations_have_not_run(fresh_database_url: str) -> None:
    assert _get_readyz(fresh_database_url) == (
        503,
        {"status": "unavailable", "checks": {"database": "ok", "migrations": "pending"}},
    )


def test_readyz_ok_when_database_is_ahead_after_a_rollback(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'from_newer_release'"))
    engine.dispose()

    assert _get_readyz(migrated_database_url)[0] == 200


def test_readyz_503_fail_when_database_unreachable() -> None:
    started = time.monotonic()
    result = _get_readyz(unreachable_database_url())

    assert result == (503, {"status": "unavailable", "checks": {"database": "fail"}})
    assert time.monotonic() - started < 5


def test_healthz_stays_ok_when_database_unreachable() -> None:
    with TestClient(create_app(make_settings(unreachable_database_url()))) as client:
        response = client.get("/api/v1/healthz")
    assert (response.status_code, response.json()["status"]) == (200, "ok")
