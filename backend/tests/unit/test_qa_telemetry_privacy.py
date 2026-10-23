"""QA end-to-end privacy checks for issue #16 (spec §14, §6.5, CLAUDE.md rule 6).

Independent of the implementer's tests: one realistic request carries every kind of sensitive
input at once (query string, JSON body, Authorization/Cookie headers, a raw user id, %-style log
arguments, unknown log fields), and the test greps *everything* the app emits for it: the real
stdout written by the handler `create_app` installs, every exported span (name, attributes,
events, links, status description), every metric data point label and the response body.
"""

import io
import json
import logging
import socket
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind

from app.main import create_app
from app.telemetry import bind_user, build_telemetry, get_logger
from app.telemetry.logs import LOG_EVENT_FIELDS
from app.telemetry.privacy import LOG_BASE_FIELDS, user_hash
from tests.conftest import Captured, captured_telemetry, make_settings, unreachable_database_url

ROUTE = "/api/v1/sessions/{session_id}/sets"
RAW_USER_ID = "4b1f6a3e-9c2d-4e8f-a7b6-5d4c3b2a1f0e"
LEAK_MARKERS = {
    "email": "qa.zelda@example.org",
    "display_name": "Zelda Quartermain",
    "weight_kg": "91.3377",
    "height_cm": "187.4377",
    "body_fat_pct": "23.7177",
    "food_name": "Smoked Paprika Tofu",
    "note": "left knee hurts after squats",
    "password": "pw-qa75-correct-horse",  # gitleaks:allow (fake)
    "authorization": "Bearer eyJxYTc1.eyJzZWNyZXQ.qa75sig",
    "cookie": "fitwise_session=qa75-cookie-value",
    "set_cookie": "fitwise_session=qa75-set-cookie-value",
    "unknown": "qa75-unknown-field-value",
    "percent_arg": "qa75-percent-arg-value",
    "raw_user_id": RAW_USER_ID,
}
# Distinctive fragments that would also reveal a partial leak.
FRAGMENTS = (
    "qa.zelda",
    "Quartermain",
    "91.3377",
    "187.4377",
    "23.7177",
    "Paprika",
    "knee hurts",
    "pw-qa75",
    "eyJxYTc1",
    "qa75sig",
    "qa75-cookie",
    "qa75-set-cookie",
    "qa75-unknown",
    "qa75-percent",
    RAW_USER_ID,
    RAW_USER_ID.replace("-", ""),
)


def _span_record(span: ReadableSpan) -> dict[str, Any]:
    return {
        "name": span.name,
        "kind": str(span.kind),
        "attributes": dict(span.attributes or {}),
        "events": [(e.name, dict(e.attributes or {})) for e in span.events],
        "links": [dict(link.attributes or {}) for link in span.links],
        "status": span.status.description,
    }


def _metric_labels(captured: Captured) -> list[dict[str, Any]]:
    data = captured.metric_reader.get_metrics_data()
    assert data is not None
    return [
        {"metric": metric.name, **dict(point.attributes or {})}
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for metric in sm.metrics
        for point in metric.data.data_points
    ]


def _assert_nothing_leaks(blob: str) -> None:
    leaked = [v for v in (*LEAK_MARKERS.values(), *FRAGMENTS) if v in blob]
    assert leaked == []


class AppStdout:
    """The exact stream the handler installed by `create_app` writes to (normally stdout)."""

    def __init__(self) -> None:
        self.stream = io.StringIO()
        [self.handler] = [
            h for h in logging.getLogger().handlers if getattr(h, "_fitwise_json_handler", False)
        ]
        assert isinstance(self.handler, logging.StreamHandler)
        self.handler.setStream(self.stream)

    def readouterr(self) -> str:
        out = self.stream.getvalue()
        self.stream.seek(0)
        self.stream.truncate()
        return out


@pytest.fixture
def qa_app(captured: Captured) -> FastAPI:
    app = captured.app
    log = get_logger("app.qa")

    @app.post(ROUTE, status_code=201)
    async def log_set(session_id: str, request: Request, response: Response) -> dict[str, bool]:
        body = await request.json()
        bind_user(RAW_USER_ID)
        # A careless call site: every sensitive field, an unknown one and the raw user id.
        log.info(
            "set logged",
            **body,
            password=LEAK_MARKERS["password"],
            token=LEAK_MARKERS["authorization"],
            cookie=request.headers.get("cookie"),
            authorization=request.headers.get("authorization"),
            user_id=RAW_USER_ID,
            unknownfield=LEAK_MARKERS["unknown"],
            outcome="created",
        )
        # Library-style logging with %-args and stdlib `extra`.
        logging.getLogger("app.qa.stdlib").warning(
            "stdlib %s %s",
            LEAK_MARKERS["percent_arg"],
            body["email"],
            extra={"weight_kg": body["weight_kg"], "note": body["note"]},
        )
        response.headers["Set-Cookie"] = LEAK_MARKERS["set_cookie"]
        return {"ok": True}

    @app.get("/api/v1/qa/boom")
    def boom(q: str) -> None:
        bind_user(RAW_USER_ID)
        raise ValueError(f"invalid input syntax for type integer: {q!r}")

    return app


@pytest.fixture
def app_stdout(qa_app: FastAPI) -> AppStdout:
    return AppStdout()


@pytest.fixture
def qa_client(qa_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(qa_app, raise_server_exceptions=False) as client:
        yield client


def _sensitive_post(client: TestClient) -> Any:
    return client.post(
        f"/api/v1/sessions/{uuid.uuid4()}/sets",
        params={"email": LEAK_MARKERS["email"], "food": LEAK_MARKERS["food_name"]},
        json={
            "email": LEAK_MARKERS["email"],
            "display_name": LEAK_MARKERS["display_name"],
            "name": LEAK_MARKERS["display_name"],
            "weight_kg": LEAK_MARKERS["weight_kg"],
            "height_cm": LEAK_MARKERS["height_cm"],
            "body_fat_pct": LEAK_MARKERS["body_fat_pct"],
            "food_name": LEAK_MARKERS["food_name"],
            "note": LEAK_MARKERS["note"],
        },
        headers={
            "Authorization": LEAK_MARKERS["authorization"],
            "Cookie": LEAK_MARKERS["cookie"],
        },
    )


def test_qa_sensitive_request_leaks_nothing_into_stdout_spans_or_metrics(
    captured: Captured, qa_client: TestClient, app_stdout: AppStdout
) -> None:
    post = _sensitive_post(qa_client)
    boom = qa_client.get("/api/v1/qa/boom", params={"q": LEAK_MARKERS["food_name"]})
    missing = qa_client.get(f"/api/v1/users/{LEAK_MARKERS['email']}/{RAW_USER_ID}")
    assert (post.status_code, boom.status_code, missing.status_code) == (201, 500, 404)

    stdout = app_stdout.readouterr()
    lines = [json.loads(line) for line in stdout.splitlines() if line]
    spans = [_span_record(s) for s in captured.spans()]
    labels = _metric_labels(captured)
    blob = json.dumps([stdout, spans, labels, boom.text, missing.text], default=str)

    _assert_nothing_leaks(blob)
    # Every stdout line is JSON with allow-listed keys only.
    assert lines
    allowed = set(LOG_BASE_FIELDS) | LOG_EVENT_FIELDS
    for line in lines:
        assert set(line) <= allowed, line
    # The user appears only as user_hash.
    expected_hash = captured.telemetry.hash_user(RAW_USER_ID)
    assert expected_hash == user_hash(RAW_USER_ID, captured.telemetry.user_hash_salt)
    assert any(line.get("user_hash") == expected_hash for line in lines)
    assert [s["attributes"].get("user_hash") for s in spans if s["kind"] == str(SpanKind.SERVER)][
        :2
    ] == [expected_hash, expected_hash]


def test_qa_access_log_is_route_template_method_status_duration_only(
    captured: Captured, qa_client: TestClient, app_stdout: AppStdout
) -> None:
    assert _sensitive_post(qa_client).status_code == 201
    qa_client.get(f"/api/v1/users/{LEAK_MARKERS['email']}?q=x")

    lines = [json.loads(line) for line in app_stdout.readouterr().splitlines() if line]
    access = [line for line in lines if line["logger"] == "app.access"]
    assert [(a["route"], a["method"], a["status"]) for a in access] == [
        (ROUTE, "POST", 201),
        ("unmatched", "GET", 404),
    ]
    for line in access:
        assert set(line) - set(LOG_BASE_FIELDS) <= {
            "route",
            "method",
            "status",
            "duration_ms",
            "user_hash",
        }
        assert "?" not in line["route"]
    assert not any(line["logger"].startswith("uvicorn.access") for line in lines)


def test_qa_uvicorn_access_logger_is_disabled_after_create_app(
    capsys: pytest.CaptureFixture[str],
) -> None:
    create_app(make_settings(unreachable_database_url()))
    access = logging.getLogger("uvicorn.access")
    access.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4", "GET", "/api/v1/x?email=a@b.co", "1.1", 200)

    assert access.disabled is True
    assert access.propagate is False
    assert access.handlers == []
    assert "uvicorn.access" not in capsys.readouterr().out


def test_qa_log_trace_id_equals_server_span_and_problem_request_id(
    captured: Captured, qa_client: TestClient, app_stdout: AppStdout
) -> None:
    app_stdout.readouterr()
    for path in ("/api/v1/qa/boom?q=x", "/api/v1/does-not-exist"):
        response = qa_client.get(path)
        assert response.status_code in (404, 500)
        request_id = response.json()["request_id"]
        lines = [json.loads(line) for line in app_stdout.readouterr().splitlines() if line]
        [server] = [
            s
            for s in captured.spans()
            if s.kind is SpanKind.SERVER and format(s.context.trace_id, "032x") == request_id
        ]
        assert lines
        assert {line["trace_id"] for line in lines} == {request_id}
        assert {line["span_id"] for line in lines} == {format(server.context.span_id, "016x")}


def test_qa_header_capture_env_vars_cannot_put_headers_on_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in (
        "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST",
        "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE",
    ):
        monkeypatch.setenv(var, ".*")
    settings = make_settings(unreachable_database_url())
    telemetry, spans, readers = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    captured = Captured(app, telemetry, spans, readers)

    @app.get("/api/v1/qa/hdr")
    def hdr(response: Response) -> dict[str, bool]:
        response.headers["Set-Cookie"] = LEAK_MARKERS["set_cookie"]
        return {"ok": True}

    with TestClient(app) as client:
        client.get(
            "/api/v1/qa/hdr",
            headers={
                "Authorization": LEAK_MARKERS["authorization"],
                "Cookie": LEAK_MARKERS["cookie"],
            },
        )

    blob = json.dumps([_span_record(s) for s in captured.spans()], default=str)
    assert "header" not in blob
    _assert_nothing_leaks(blob)


def test_qa_without_endpoint_no_socket_is_ever_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    connects: list[Any] = []
    real_connect = socket.socket.connect

    def recording_connect(self: socket.socket, address: Any) -> Any:
        connects.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", recording_connect)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    settings = make_settings(unreachable_database_url())
    assert settings.otel_exporter_otlp_endpoint is None
    telemetry = build_telemetry(settings)
    app = create_app(settings, telemetry)

    @app.get("/api/v1/qa/ok")
    def ok() -> dict[str, bool]:
        with telemetry.engine_span("targets"):
            telemetry.metrics.set_logged()
        return {"ok": True}

    with TestClient(app) as client:
        for _ in range(5):
            assert client.get("/api/v1/qa/ok").status_code == 200
    telemetry.meter_provider.force_flush()
    telemetry.tracer_provider.force_flush()

    assert connects == []
