"""Swagger UI and the generated OpenAPI document are not served in prod."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings, unreachable_database_url


@pytest.mark.parametrize(
    ("app_env", "served"), [("local", True), ("test", True), ("dev", True), ("prod", False)]
)
def test_docs_only_outside_prod(app_env: str, served: bool) -> None:
    settings = make_settings(
        unreachable_database_url(), app_env=app_env, user_hash_salt="a-long-random-test-salt"
    )
    app = create_app(settings)
    with TestClient(app) as client:
        docs = client.get("/api/v1/docs")
        spec = client.get("/api/v1/openapi.json")
        health = client.get("/api/v1/healthz")

    expected = 200 if served else 404
    assert (docs.status_code, spec.status_code) == (expected, expected)
    assert health.status_code == 200
