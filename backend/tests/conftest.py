import socket
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def closed_port() -> int:
    """A local TCP port with nothing listening on it (connections are refused immediately)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def make_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        database_connect_timeout_seconds=1,
        app_env="test",
        _env_file=None,
    )


def unreachable_database_url() -> str:
    return f"postgresql+psycopg://fitwise:unused@127.0.0.1:{closed_port()}/fitwise"


@pytest.fixture
def offline_app() -> FastAPI:
    """The app wired to a database that is not reachable (unit tests never need Postgres)."""
    return create_app(make_settings(unreachable_database_url()))


@pytest.fixture
def offline_client(offline_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(offline_app) as client:
        yield client
