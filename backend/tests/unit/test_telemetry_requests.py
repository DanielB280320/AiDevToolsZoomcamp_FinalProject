"""Per-request telemetry (issue #16): server span, `http_server_duration`, access log, privacy."""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult, MetricsData
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from app.telemetry import bind_user, build_telemetry
from app.telemetry import setup as telemetry_setup
from app.telemetry.metrics import UNMATCHED_ROUTE
from app.telemetry.privacy import METRIC_ATTRIBUTES, user_hash
from tests.conftest import Captured, JsonLogs, make_settings, unreachable_database_url

SETS_ROUTE = "/api/v1/_test/sessions/{session_id}/sets"
SESSION_ID = "6f1c2a8e-0b7d-4c55-9a51-3d2f0e7b9c11"
USER_ID = uuid.UUID("0d9e8f7a-6b5c-4d3e-8f2a-1b0c9d8e7f6a")
# Values that must never show up in any exported span, metric or log line.
SECRETS = {
    "query": "q-secret-chicken-breast",
    "body": "body-secret-feeling-tired",
    "authorization": "Bearer auth-secret-eyJhbGciOi",
    "cookie": "fitwise_session=cookie-secret-123",
    "set_cookie": "fitwise_session=set-cookie-secret-456",
    "user_agent": "ua-secret-browser",
}


@pytest.fixture
def client(captured: Captured) -> Iterator[TestClient]:
    app = captured.app

    @app.post(SETS_ROUTE, status_code=201)
    def log_set(session_id: uuid.UUID, body: dict[str, Any]) -> dict[str, str]:
        bind_user(USER_ID)  # what the auth dependency does once the cookie is verified
        return {"session_id": str(session_id)}

    @app.get("/api/v1/_test/boom")
    def boom() -> None:
        raise RuntimeError("database said: weight 84.2 kg body-secret-feeling-tired")

    with TestClient(app) as test_client:
        yield test_client


def _post_set(client: TestClient) -> Any:
    response = client.post(
        f"/api/v1/_test/sessions/{SESSION_ID}/sets?food={SECRETS['query']}",
        json={"note": SECRETS["body"], "weight_kg": 84.2},
        headers={
            "Authorization": SECRETS["authorization"],
            "Cookie": SECRETS["cookie"],
            "User-Agent": SECRETS["user_agent"],
        },
    )
    assert response.status_code == 201
    return response


def _span_dump(span: ReadableSpan) -> str:
    return json.dumps(
        {
            "name": span.name,
            "attributes": dict(span.attributes or {}),
            "events": [(e.name, dict(e.attributes or {})) for e in span.events],
            "status": span.status.description,
        },
        default=str,
    )


def test_a_request_gives_a_server_span_a_duration_observation_and_a_correlated_log_line(
    captured: Captured, client: TestClient, json_logs: JsonLogs
) -> None:
    _post_set(client)

    [server] = captured.server_spans()
    assert server.name == f"POST {SETS_ROUTE}"
    assert server.attributes is not None
    assert server.attributes["http.route"] == SETS_ROUTE

    [point] = captured.metric_points("http_server_duration")
    assert dict(point.attributes) == {"route": SETS_ROUTE, "method": "POST", "status": 201}
    assert point.count == 1

    [access] = json_logs.with_message("request")
    trace_id = format(server.context.trace_id, "032x")
    assert access["trace_id"] == trace_id
    assert access["span_id"] == format(server.context.span_id, "016x")
    assert access["route"] == SETS_ROUTE
    assert (access["method"], access["status"]) == ("POST", 201)
    assert access["duration_ms"] >= 0


def test_route_template_is_used_and_raw_ids_never_become_labels(
    captured: Captured, client: TestClient, json_logs: JsonLogs
) -> None:
    _post_set(client)
    client.get(f"/api/v1/athletes/{SESSION_ID}/unknown-thing?x={SECRETS['query']}")

    labels = [dict(p.attributes) for p in captured.metric_points("http_server_duration")]
    assert {"route": UNMATCHED_ROUTE, "method": "GET", "status": 404} in labels
    for attributes in labels:
        assert set(attributes) <= METRIC_ATTRIBUTES
        assert SESSION_ID not in json.dumps(attributes)
    assert SESSION_ID not in json_logs.text
    for span in captured.spans():
        assert SESSION_ID not in _span_dump(span)


def test_spans_carry_no_bodies_query_strings_cookies_or_auth_headers(
    captured: Captured, client: TestClient
) -> None:
    _post_set(client)

    spans = captured.spans()
    assert spans
    for span in spans:
        dump = _span_dump(span)
        for secret in (*SECRETS.values(), "84.2", "food="):
            assert secret not in dump, f"{secret!r} leaked into span {span.name}"
        keys = set(span.attributes or {})
        assert not {k for k in keys if "header" in k or "query" in k or "user_agent" in k}
        assert not keys & {"http.target", "http.url", "url.full", "url.path", "url.query"}
        assert not keys & {"http.client_ip", "client.address", "net.peer.ip"}


def test_user_hash_is_on_the_access_log_and_server_span_and_the_raw_id_is_not(
    captured: Captured, client: TestClient, json_logs: JsonLogs
) -> None:
    _post_set(client)

    expected = user_hash(USER_ID, make_settings("postgresql://h/d").user_hash_salt_bytes)
    [access] = json_logs.with_message("request")
    assert access["user_hash"] == expected
    [server] = captured.server_spans()
    assert server.attributes is not None
    assert server.attributes["user_hash"] == expected
    assert str(USER_ID) not in json_logs.text
    assert str(USER_ID) not in _span_dump(server)


def test_an_unhandled_error_is_recorded_as_500_without_the_exception_message(
    captured: Captured, client: TestClient, json_logs: JsonLogs
) -> None:
    response = client.get("/api/v1/_test/boom")

    assert response.status_code == 500
    [server] = captured.server_spans()
    assert server.attributes is not None
    assert server.attributes["http.status_code"] == 500
    assert "database said" not in _span_dump(server)
    assert server.status.description is None
    [point] = captured.metric_points("http_server_duration")
    assert dict(point.attributes)["status"] == 500
    [error] = json_logs.with_message("unhandled exception")
    assert error["error_type"] == "RuntimeError"
    assert error["level"] == "error"
    assert error["trace_id"] == format(server.context.trace_id, "032x")
    assert "database said" not in json_logs.text
    assert "84.2" not in json_logs.text
    assert "Traceback" not in json_logs.text


def test_problem_request_id_is_the_trace_id(captured: Captured, client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    [server] = captured.server_spans()
    assert response.json()["request_id"] == format(server.context.trace_id, "032x")


def test_health_probes_are_neither_traced_nor_access_logged_when_healthy(
    captured: Captured, client: TestClient, json_logs: JsonLogs
) -> None:
    assert client.get("/api/v1/healthz").status_code == 200

    assert captured.spans() == []
    assert json_logs.with_message("request") == []
    [point] = captured.metric_points("http_server_duration")
    assert dict(point.attributes) == {"route": "/api/v1/healthz", "method": "GET", "status": 200}


def test_readiness_failure_is_logged_with_the_error_type_only(
    client: TestClient, json_logs: JsonLogs
) -> None:
    response = client.get("/api/v1/readyz")

    assert response.status_code == 503
    [failure] = json_logs.with_message("readiness check failed")
    assert failure["check"] == "database"
    assert failure["error_type"] == "OperationalError"
    assert failure["level"] == "warning"
    assert "127.0.0.1" not in json_logs.text
    assert "fitwise:unused" not in json_logs.text
    [access] = json_logs.with_message("request")
    assert (access["route"], access["status"]) == ("/api/v1/readyz", 503)


def test_resource_carries_env_service_name_and_version(captured: Captured) -> None:
    attributes = captured.telemetry.resource.attributes

    assert attributes["env"] == "test"
    assert attributes["deployment.environment.name"] == "test"
    assert attributes["service.name"] == "fitwise-backend"
    assert attributes["service.version"] == "dev"


@pytest.mark.parametrize("env", ["local", "dev", "prod"])
def test_resource_env_and_version_come_from_settings(env: str) -> None:
    settings = make_settings(
        unreachable_database_url(),
        app_env=env,
        app_version="3f2a9c1",
        user_hash_salt="a-long-random-test-salt",
    )
    telemetry = build_telemetry(settings)

    attributes = telemetry.resource.attributes
    assert (attributes["env"], attributes["service.version"]) == (env, "3f2a9c1")


def test_without_an_otlp_endpoint_nothing_is_exported() -> None:
    telemetry = build_telemetry(make_settings(unreachable_database_url()))

    assert telemetry.tracer_provider._active_span_processor._span_processors == ()
    assert tuple(telemetry.meter_provider._metric_readers) == ()
    # Spans still get real ids for log correlation and Problem.request_id.
    with telemetry.tracer.start_as_current_span("x") as span:
        assert span.get_span_context().is_valid


class _FakeSpanExporter(InMemorySpanExporter):
    def __init__(self, *, endpoint: str) -> None:
        super().__init__()
        self.endpoint = endpoint


class _FakeMetricExporter(MetricExporter):
    def __init__(self, *, endpoint: str) -> None:
        super().__init__()
        self.endpoint = endpoint
        self.exported: list[MetricsData] = []

    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **_: Any) -> Any:
        self.exported.append(metrics_data)
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **_: Any) -> None:
        return None


def test_with_an_otlp_endpoint_traces_and_metrics_go_to_the_collector_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, Any] = {}

    def span_exporter(*, endpoint: str) -> _FakeSpanExporter:
        exporter = _FakeSpanExporter(endpoint=endpoint)
        created["spans"] = exporter
        return exporter

    def metric_exporter(*, endpoint: str) -> _FakeMetricExporter:
        exporter = _FakeMetricExporter(endpoint=endpoint)
        created["metrics"] = exporter
        return exporter

    monkeypatch.setattr(telemetry_setup, "OTLPSpanExporter", span_exporter)
    monkeypatch.setattr(telemetry_setup, "OTLPMetricExporter", metric_exporter)
    settings = make_settings(
        unreachable_database_url(), otel_exporter_otlp_endpoint="http://otel-collector:4318/"
    )

    telemetry = build_telemetry(settings)
    with telemetry.tracer.start_as_current_span("x") as span:
        span.set_attribute("email", "ann@example.com")
    telemetry.shutdown()  # flushes the batch processor and the periodic reader

    assert created["spans"].endpoint == "http://otel-collector:4318/v1/traces"
    assert created["metrics"].endpoint == "http://otel-collector:4318/v1/metrics"
    [exported] = created["spans"].get_finished_spans()
    assert dict(exported.attributes or {}) == {}  # the sanitizing wrapper is in the OTLP path
    assert created["metrics"].exported


def test_custom_attributes_are_kept_only_in_the_fitwise_namespace(captured: Captured) -> None:
    with captured.telemetry.engine_span("progression") as span:
        span.set_attribute("fitwise.engine.rule", "double")
        span.set_attribute("fitwise.weight_kg", 84.2)
        span.set_attribute("weight_kg", 84.2)
        span.set_attribute("email", "ann@example.com")

    [engine] = captured.spans()
    assert engine.name == "engine.progression"
    assert engine.kind is SpanKind.INTERNAL
    assert dict(engine.attributes or {}) == {"fitwise.engine.rule": "double"}
    assert engine.status.status_code is StatusCode.UNSET
