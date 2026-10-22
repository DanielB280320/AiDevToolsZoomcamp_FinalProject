"""Span export filter: every exported span passes through `sanitize_span` (spec §6.5).

The instrumentations are configured not to capture headers or bodies, but an env var
(`OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*`), a library upgrade or an exception message can
still put data on a span. So the exporter keeps only allow-listed attributes, scrubs outgoing URLs
and SQL text, drops exception messages/stack traces and status descriptions (a database error
message can quote a submitted value), and names server spans by route template.
"""

from collections.abc import Mapping, Sequence

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, Status
from opentelemetry.util.types import AttributeValue

from app.telemetry.privacy import (
    CLIENT_ONLY_SPAN_ATTRIBUTES,
    SQL_SPAN_ATTRIBUTES,
    is_allowed_span_attribute,
    scrub_sql,
    scrub_text,
    scrub_url,
)


def sanitize_attributes(
    attributes: Mapping[str, AttributeValue] | None, *, kind: SpanKind = SpanKind.INTERNAL
) -> dict[str, AttributeValue]:
    kept: dict[str, AttributeValue] = {}
    for key, value in (attributes or {}).items():
        if not is_allowed_span_attribute(key):
            continue
        if key in CLIENT_ONLY_SPAN_ATTRIBUTES:
            if kind is not SpanKind.CLIENT or not isinstance(value, str):
                continue
            value = scrub_url(value)
        elif key in SQL_SPAN_ATTRIBUTES and isinstance(value, str):
            value = scrub_sql(value)
        elif isinstance(value, str):
            value = scrub_text(value)
        kept[key] = value
    return kept


def _span_name(span: ReadableSpan, attributes: Mapping[str, AttributeValue]) -> str:
    if span.kind is SpanKind.SERVER:
        method = attributes.get("http.request.method") or attributes.get("http.method") or ""
        route = attributes.get("http.route")
        return f"{method} {route}".strip() if route else str(method) or "HTTP"
    return scrub_text(span.name)


def sanitize_span(span: ReadableSpan) -> ReadableSpan:
    attributes = sanitize_attributes(span.attributes, kind=span.kind)
    events = [
        Event(event.name, sanitize_attributes(event.attributes), event.timestamp)
        for event in span.events
    ]
    return ReadableSpan(
        name=_span_name(span, attributes),
        context=span.get_span_context(),
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=events,
        links=span.links,
        kind=span.kind,
        status=Status(span.status.status_code),  # no description
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class SanitizingSpanExporter(SpanExporter):
    """Wraps the real exporter (OTLP in deployments, in-memory in tests)."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([sanitize_span(span) for span in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)
