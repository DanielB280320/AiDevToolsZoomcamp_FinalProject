"""/readyz stays bounded when the database accepts TCP but never answers (QA, issue #6).

A refused connection fails instantly; a hung server (blackholed host, stalled Postgres) is the
case that `DATABASE_CONNECT_TIMEOUT_SECONDS` exists for. Compose health checks and the deploy
smoke test need a prompt 503 instead of a hung probe.
"""

import socket
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings
from tests.contract import assert_matches_schema


@pytest.fixture
def silent_server_port() -> Iterator[int]:
    """A port whose kernel completes the TCP handshake but nothing ever replies."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)  # never accept(): the startup packet is never answered
        port: int = sock.getsockname()[1]
        yield port


def test_readyz_503_within_connect_timeout_when_database_hangs(silent_server_port: int) -> None:
    url = f"postgresql+psycopg://fitwise:unused@127.0.0.1:{silent_server_port}/fitwise"
    settings = make_settings(url)  # connect timeout 1 s

    started = time.monotonic()
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/readyz")
    elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "fail"}}
    assert_matches_schema(response.json(), "Readiness")
    assert elapsed < settings.database_connect_timeout_seconds + 4


def test_healthz_does_not_wait_for_a_hung_database(silent_server_port: int) -> None:
    url = f"postgresql+psycopg://fitwise:unused@127.0.0.1:{silent_server_port}/fitwise"

    started = time.monotonic()
    with TestClient(create_app(make_settings(url))) as client:
        response = client.get("/api/v1/healthz")

    assert (response.status_code, response.json()["status"]) == (200, "ok")
    assert time.monotonic() - started < 1
