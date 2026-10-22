"""QA (issue #16): a PostgreSQL error that quotes user input never reaches telemetry.

Postgres echoes the offending value in its message (`invalid input syntax for type integer:
"..."`). The request goes through the full app over HTTP; the test greps stdout (the handler
`create_app` installs), every exported span (attributes, events, status description), every
metric label and the Problem body.
"""

import io
import json
import logging

from fastapi.testclient import TestClient
from opentelemetry.trace import SpanKind, StatusCode
from sqlalchemy import text

from app.main import create_app
from tests.conftest import captured_telemetry, make_settings

USER_INPUT = "qa75-food-Smoked-Paprika-Tofu"
LITERAL_INPUT = "qa75-literal-Grandmas-lasagne"


def test_qa_db_error_quoting_user_input_leaks_nothing(migrated_database_url: str) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    [handler] = [
        h for h in logging.getLogger().handlers if getattr(h, "_fitwise_json_handler", False)
    ]
    assert isinstance(handler, logging.StreamHandler)
    stdout = io.StringIO()
    handler.setStream(stdout)

    @app.get("/api/v1/qa/cast")
    def cast(v: str) -> None:
        with app.state.engine.connect() as connection:
            connection.execute(text("SELECT CAST(:v AS integer)"), {"v": v})

    @app.get("/api/v1/qa/cast-literal")
    def cast_literal(v: str) -> None:
        # Deliberately inlined: the statement text itself holds the user value.
        with app.state.engine.connect() as connection:
            connection.execute(text(f"SELECT CAST('{v}' AS integer)"))

    with TestClient(app, raise_server_exceptions=False) as client:
        bound = client.get("/api/v1/qa/cast", params={"v": USER_INPUT})
        literal = client.get("/api/v1/qa/cast-literal", params={"v": LITERAL_INPUT})
    assert (bound.status_code, literal.status_code) == (500, 500)

    spans = span_exporter.get_finished_spans()
    db_spans = [s for s in spans if s.kind is SpanKind.CLIENT and "CAST" in str(s.attributes)]
    assert len(db_spans) == 2
    assert all(s.status.status_code is StatusCode.ERROR for s in db_spans)
    data = metric_reader.get_metrics_data()
    labels = [
        dict(point.attributes or {})
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for metric in sm.metrics
        for point in metric.data.data_points
    ]
    blob = json.dumps(
        [
            stdout.getvalue(),
            [
                (
                    s.name,
                    dict(s.attributes or {}),
                    [(e.name, dict(e.attributes or {})) for e in s.events],
                    s.status.description,
                )
                for s in spans
            ],
            labels,
            bound.text,
            literal.text,
        ],
        default=str,
    )
    for value in (USER_INPUT, LITERAL_INPUT, "Paprika", "lasagne", "invalid input syntax"):
        assert value not in blob
    errors = [json.loads(line) for line in stdout.getvalue().splitlines() if "unhandled" in line]
    assert [line["error_type"] for line in errors] == ["DataError", "DataError"]
    assert {line["trace_id"] for line in errors} == {
        bound.json()["request_id"],
        literal.json()["request_id"],
    }
