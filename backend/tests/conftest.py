import io
import json
import logging
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from app.config import Settings
from app.main import create_app
from app.telemetry import Telemetry, build_telemetry
from app.telemetry.logs import JsonFormatter


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


@dataclass
class Captured:
    """An app wired to in-memory exporters, plus helpers to read what it exported."""

    app: FastAPI
    telemetry: Telemetry
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader

    def spans(self) -> list[ReadableSpan]:
        return list(self.span_exporter.get_finished_spans())

    def server_spans(self) -> list[ReadableSpan]:
        return [s for s in self.spans() if s.kind is SpanKind.SERVER]

    def metric_points(self, name: str) -> list[Any]:
        data = self.metric_reader.get_metrics_data()
        assert data is not None
        return [
            point
            for resource_metrics in data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
            if metric.name == name
            for point in metric.data.data_points
        ]

    def metric_names(self) -> set[str]:
        data = self.metric_reader.get_metrics_data()
        assert data is not None
        return {
            metric.name
            for resource_metrics in data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
        }


def captured_telemetry(settings: Settings) -> tuple[Telemetry, InMemorySpanExporter, Any]:
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    telemetry = build_telemetry(
        settings, span_exporter=span_exporter, metric_readers=(metric_reader,)
    )
    return telemetry, span_exporter, metric_reader


@pytest.fixture
def captured() -> Captured:
    """The offline app with telemetry captured in memory (no collector, no network)."""
    settings = make_settings(unreachable_database_url())
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    return Captured(app, telemetry, span_exporter, metric_reader)


class JsonLogs:
    """JSON lines written through the app's formatter while the fixture is active."""

    def __init__(self, stream: io.StringIO) -> None:
        self._stream = stream

    @property
    def text(self) -> str:
        return self._stream.getvalue()

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.text.splitlines() if line]

    def with_message(self, message: str) -> list[dict[str, Any]]:
        return [line for line in self.lines() if line["message"] == message]


@pytest.fixture
def json_logs() -> Iterator[JsonLogs]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(env="test", service="fitwise-backend", version="dev"))
    root = logging.getLogger()
    root.addHandler(handler)
    app_logger = logging.getLogger("app")
    previous_level = app_logger.level
    app_logger.setLevel(logging.DEBUG)
    try:
        yield JsonLogs(stream)
    finally:
        root.removeHandler(handler)
        app_logger.setLevel(previous_level)
