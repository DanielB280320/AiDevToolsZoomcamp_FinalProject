from __future__ import annotations

import base64
import json
import shlex
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from responder.app import Responder, create_app
from responder.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
USER = "grafana"
PASSWORD = "test-password"
AUTH = {"Authorization": "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()}

# The collector keeps only the message as the line body, so this is what Loki returns.
EMAIL_LINE = "boom, contact alice@example.com"


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


class StubBackends:
    """One HTTP server standing in for Prometheus, Loki and Tempo (paths tell them apart)."""

    def __init__(self) -> None:
        self.down: set[str] = set()  # "prometheus" | "loki" | "tempo" -> answer 503
        self.bad_queries: list[str] = []
        self.requests: list[tuple[str, dict[str, list[str]]]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                stub.requests.append((parsed.path, parse_qs(parsed.query)))
                if parsed.path == "/loki/api/v1/query_range":
                    # Selector and filter must match what the collector/Loki really expose
                    # (collector config.yaml, service-health dashboard): index labels
                    # service_name/env, level via detected_level; never a text match on the body.
                    query = parse_qs(parsed.query).get("query", [""])[0]
                    expected = (
                        '{service_name="fitwise-backend", env="prod"}'
                        ' | detected_level=~"error|critical|fatal"'
                    )
                    if query != expected:
                        stub.bad_queries.append(query)
                        self.send_response(400)
                        self.end_headers()
                        return
                backend, body = {
                    "/api/v1/query_range": (
                        "prometheus",
                        {"status": "success", "data": {"resultType": "matrix", "result": []}},
                    ),
                    "/loki/api/v1/query_range": (
                        "loki",
                        {
                            "status": "success",
                            "data": {
                                "resultType": "streams",
                                "result": [{"stream": {}, "values": [["1", EMAIL_LINE]]}],
                            },
                        },
                    ),
                    "/api/search": (
                        "tempo",
                        {"traces": [{"traceID": "abc123"}, {"traceID": "def456"}]},
                    ),
                }.get(parsed.path, ("", {}))
                if not backend or backend in stub.down:
                    self.send_response(503 if backend else 404)
                    self.end_headers()
                    return
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stubs() -> Iterator[StubBackends]:
    stub = StubBackends()
    yield stub
    stub.close()


@pytest.fixture
def launcher_log(tmp_path: Path) -> Path:
    return tmp_path / "launcher.log"


@pytest.fixture
def settings(tmp_path: Path, stubs: StubBackends, launcher_log: Path) -> Settings:
    cmd = shlex.join(["sh", "-c", f'echo "$ONCALL_INCIDENT_ID" >> {launcher_log}', "launcher"])
    return replace(
        Settings.from_env(
            {
                "ONCALL_WEBHOOK_USER": USER,
                "ONCALL_WEBHOOK_PASSWORD": PASSWORD,
                "ONCALL_INCIDENTS_DIR": str(tmp_path / "incidents"),
                "ONCALL_PROMETHEUS_URL": stubs.url,
                "ONCALL_LOKI_URL": stubs.url,
                "ONCALL_TEMPO_URL": stubs.url,
                "ONCALL_LAUNCHER_CMD": cmd,
                "ONCALL_CAPTURE_TIMEOUT_S": "3",
            }
        ),
    )


@pytest.fixture
def make_client() -> Iterator[Callable[[Settings], TestClient]]:
    clients: list[TestClient] = []

    def factory(settings: Settings) -> TestClient:
        client = TestClient(create_app(settings), headers=AUTH)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()


@pytest.fixture
def client(settings: Settings, make_client: Callable[[Settings], TestClient]) -> TestClient:
    return make_client(settings)


def responder_of(client: TestClient) -> Responder:
    responder: Responder = client.app.state.responder  # type: ignore[attr-defined]
    return responder


def incident_dirs(settings: Settings) -> list[Path]:
    if not settings.incidents_dir.exists():
        return []
    return sorted(p for p in settings.incidents_dir.iterdir() if p.is_dir() and p.name != "open")
