"""SQL spans against real PostgreSQL (issue #16): no bound values, even in error messages."""

import json

import pytest
from fastapi.testclient import TestClient
from opentelemetry.trace import SpanKind
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from tests.conftest import captured_telemetry, make_settings

SECRET_EMAIL = "ann.athlete@example.com"


def test_sql_spans_and_logs_never_hold_bound_values(migrated_database_url: str) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, spans, _ = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    engine = app.state.engine

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE t_account (email text UNIQUE, weight_kg numeric)"))
        connection.execute(
            text("INSERT INTO t_account VALUES (:email, :weight)"),
            {"email": SECRET_EMAIL, "weight": 84.2371},
        )
    # Postgres puts the duplicate value in the error: Key (email)=(ann...) already exists.
    with pytest.raises(IntegrityError, match="already exists"), engine.begin() as connection:
        connection.execute(
            text("INSERT INTO t_account VALUES (:email, :weight)"),
            {"email": SECRET_EMAIL, "weight": 84.2371},
        )
    with TestClient(app) as client:
        assert client.get("/api/v1/readyz").status_code == 200

    db_spans = [s for s in spans.get_finished_spans() if s.kind is SpanKind.CLIENT]
    assert len(db_spans) >= 3
    for span in db_spans:
        attributes = dict(span.attributes or {})
        assert attributes["db.system"] == "postgresql"
        dump = json.dumps(
            [attributes, span.status.description, [dict(e.attributes or {}) for e in span.events]],
            default=str,
        )
        assert SECRET_EMAIL not in dump
        assert "84.2371" not in dump
        assert "already exists" not in dump
    inserts = [
        str(dict(s.attributes or {})["db.statement"]) for s in db_spans if "INSERT" in s.name
    ]
    assert inserts
    assert all("%(email)s" in statement for statement in inserts)
