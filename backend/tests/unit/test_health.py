from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.contract import assert_matches_schema


def test_healthz_returns_ok_without_touching_the_database(
    offline_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_connect(*_: Any, **__: Any) -> None:
        raise AssertionError("/healthz must not touch the database")

    monkeypatch.setattr(offline_app.state.engine, "connect", fail_connect)

    with TestClient(offline_app) as client:
        response = client.get("/api/v1/healthz")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}
    assert_matches_schema(response.json(), "Health")


def test_healthz_is_only_served_under_api_v1(offline_client: TestClient) -> None:
    assert offline_client.get("/healthz").status_code == 404
