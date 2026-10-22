"""Helpers for the auth/me integration tests."""

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from app.main import create_app
from tests.conftest import make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock

# 2026-10-22 09:00 UTC; Europe/Madrid is UTC+2 that day.
NOW = dt.datetime(2026, 10, 22, 9, 0, tzinfo=dt.UTC)
PASSWORD = "correct-horse-battery"


def signup_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": "ana@x.test",
        "password": PASSWORD,
        "display_name": "Ana",
        "role": "athlete",
        "birth_date": "1995-04-12",
        "units": "metric",
        "timezone": "Europe/Madrid",
        "accept_disclaimer": True,
    }
    body.update(overrides)
    return body


@dataclass
class Api:
    app: FastAPI
    client: TestClient
    clock: FakeClock

    def signup(self, **overrides: Any) -> Response:
        return self.client.post("/api/v1/auth/signup", json=signup_body(**overrides))

    def login(self, email: str = "ana@x.test", password: str = PASSWORD) -> Response:
        return self.client.post("/api/v1/auth/login", json={"email": email, "password": password})

    def new_client(self) -> TestClient:
        """A second browser: same app, empty cookie jar."""
        return TestClient(self.app)


@pytest.fixture
def api_factory(migrated_database_url: str) -> Iterator[Any]:
    clients: list[TestClient] = []

    def build(**settings: Any) -> Api:
        app = create_app(make_settings(migrated_database_url, **settings))
        clock = FakeClock(NOW)
        app.state.clock = clock
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return Api(app=app, client=client, clock=clock)

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def api(api_factory: Any) -> Api:
    built: Api = api_factory()
    return built


def problem(response: Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, Any] = response.json()
    assert_matches_schema(body, "Problem")
    assert body["code"] == code
    return body


def field_errors(body: dict[str, Any]) -> set[tuple[str, str]]:
    return {(error["field"], error["code"]) for error in body.get("errors", [])}
