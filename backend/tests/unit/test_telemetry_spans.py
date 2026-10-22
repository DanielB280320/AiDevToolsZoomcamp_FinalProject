"""Span scrubbing for SQL and outgoing HTTP (issue #16 AC: no bodies, queries, headers, params)."""

import json
from typing import Any

import httpx2 as httpx
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.telemetry import instrument_http_client
from app.telemetry.privacy import scrub_sql, scrub_url
from app.telemetry.setup import instrument_engine
from tests.conftest import Captured

SECRET_EMAIL = "ann.athlete@example.com"
SECRET_FOOD = "grandmas-lasagne"


def _dump(span: ReadableSpan) -> str:
    return json.dumps(
        {
            "name": span.name,
            "attributes": dict(span.attributes or {}),
            "events": [(e.name, dict(e.attributes or {})) for e in span.events],
            "status": span.status.description,
        },
        default=str,
    )


def test_sql_spans_have_placeholders_and_never_bound_values(captured: Captured) -> None:
    engine = create_engine("sqlite://")
    instrument_engine(engine, captured.telemetry)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE account (email TEXT UNIQUE, weight_kg REAL)"))
        connection.execute(
            text("INSERT INTO account VALUES (:email, :weight)"),
            {"email": SECRET_EMAIL, "weight": 84.2371},
        )
        # An inlined literal (never done in app code, §6.4) is still masked in the span.
        connection.execute(text("SELECT * FROM account WHERE email = 'ann.athlete@example.com'"))
        with pytest.raises(SQLAlchemyError):
            connection.execute(
                text("INSERT INTO account VALUES (:email, :weight)"),
                {"email": SECRET_EMAIL, "weight": 84.2371},
            )

    spans = [s for s in captured.spans() if s.kind is SpanKind.CLIENT]
    assert len(spans) == 4
    statements = [dict(s.attributes or {})["db.statement"] for s in spans]
    assert statements[1] == "INSERT INTO account VALUES (?, ?)"
    assert statements[2] == "SELECT * FROM account WHERE email = '?'"
    for span in spans:
        dump = _dump(span)
        assert SECRET_EMAIL not in dump
        assert "84.2371" not in dump
        assert span.status.description is None
        assert not any(k.startswith("db.query.parameter") for k in span.attributes or {})


def test_outgoing_http_spans_drop_query_string_and_headers(captured: Captured) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"products": []}, headers={"Set-Cookie": "s=zz-cookie"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    instrument_http_client(client, captured.telemetry)
    client.get(
        f"https://user:pw@world.openfoodfacts.org/api/v2/search?search_terms={SECRET_FOOD}#frag",
        headers={"Authorization": "Bearer zz-token", "Cookie": "s=zz-cookie"},
    )

    [span] = [s for s in captured.spans() if s.kind is SpanKind.CLIENT]
    attributes: dict[str, Any] = dict(span.attributes or {})
    url = attributes.get("url.full") or attributes.get("http.url")
    assert url == "https://world.openfoodfacts.org/api/v2/search"
    dump = _dump(span)
    for secret in (SECRET_FOOD, "zz-token", "zz-cookie", "pw@", "frag", "search_terms"):
        assert secret not in dump


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://h/p?q=1", "https://h/p"),
        ("https://u:p@h:8443/p#x", "https://h:8443/p"),
        ("http://h", "http://h"),
        ("http://[::1", ""),
    ],
)
def test_scrub_url(url: str, expected: str) -> None:
    assert scrub_url(url) == expected


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", "SELECT 1"),
        ("WHERE a = %(email)s", "WHERE a = %(email)s"),
        ("WHERE a = 'x' AND b = 'it''s'", "WHERE a = '?' AND b = '?'"),
    ],
)
def test_scrub_sql(sql: str, expected: str) -> None:
    assert scrub_sql(sql) == expected
