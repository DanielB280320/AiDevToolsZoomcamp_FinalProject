"""QA: more hostile OTLP payloads against the prod collector (#130, rule 6).

Extends test_collector_hardening_runtime.py (same fixture: real collector image, file exporters,
ephemeral port). `xfail(strict=True)` cases are known gaps tracked in #151; they start passing,
and must then lose the marker, when #151 lands.
"""

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_collector_hardening_runtime as runtime
from tests.unit.test_collector_hardening_runtime import (
    EMAIL,
    _attrs,
    _image_available,
    _post,
    _read,
)

collector = runtime.collector  # same module-scoped fixture: one collector container per module
B64_EMAIL = base64.b64encode(EMAIL.encode()).decode()

pytestmark = pytest.mark.skipif(not _image_available(), reason="docker / collector image missing")

Collector = tuple[str, Path]
RESOURCE_KEYS = {"service.name", "service.version", "deployment.environment.name", "env"}
TOP = {"logs": "resourceLogs", "traces": "resourceSpans", "metrics": "resourceMetrics"}


def _records(text: str, marker: str) -> list[dict[str, Any]]:
    return [
        rec
        for line in text.splitlines()
        if marker in line
        for rl in json.loads(line)["resourceLogs"]
        for sl in rl["scopeLogs"]
        for rec in sl["logRecords"]
    ]


def _logs(resource: dict[str, Any], records: list[Any], scope: Any = None) -> Any:
    scope_logs: dict[str, Any] = {"logRecords": records}
    if scope is not None:
        scope_logs["scope"] = scope
    return {"resourceLogs": [{"resource": resource, "scopeLogs": [scope_logs]}]}


def test_nested_array_and_bytes_bodies_are_blanked(collector: Collector) -> None:
    url, out = collector
    nested = {"kvlistValue": {"values": [{"key": "a", "value": {"kvlistValue": {"values": [
        {"key": "b", "value": {"arrayValue": {"values": [{"stringValue": f"NESTED {EMAIL}"}]}}}
    ]}}}]}}  # fmt: skip
    array = {"arrayValue": {"values": [{"stringValue": EMAIL}]}}
    records = [
        {"body": nested, "attributes": _attrs(route="/qa-nested")},
        {"body": array, "attributes": _attrs(route="/qa-array")},
        {"body": {"bytesValue": B64_EMAIL}, "attributes": _attrs(route="/qa-bytes")},
        {"body": {"stringValue": "qa-bodies-marker"}},
    ]
    _post(url, "/v1/logs", _logs({}, records))
    text = _read(out, "logs", "qa-bodies-marker")
    exported = _records(text, "qa-bodies-marker")
    assert EMAIL not in json.dumps(exported)
    assert B64_EMAIL not in text
    routes = {
        a["value"]["stringValue"]: r["body"] for r in exported for a in r.get("attributes", [])
    }
    assert routes == {r: {"stringValue": ""} for r in ("/qa-nested", "/qa-array", "/qa-bytes")}


def test_records_with_only_disallowed_attributes_or_nothing_are_dropped(
    collector: Collector,
) -> None:
    url, out = collector
    records = [
        {"attributes": _attrs(note="QA-DROP-1", food_name="QA-DROP-2", email=EMAIL)},
        {},
        {"body": {"intValue": "4242424242"}},
        {"body": {"kvlistValue": {"values": []}}, "attributes": _attrs(weight_kg="QA-DROP-3")},
        {"body": {"stringValue": "qa-drop-marker"}},
    ]
    _post(url, "/v1/logs", _logs({}, records))
    text = _read(out, "logs", "qa-drop-marker")
    exported = _records(text, "qa-drop-marker")
    assert [r["body"] for r in exported] == [{"stringValue": "qa-drop-marker"}]
    assert "QA-DROP" not in text
    assert "4242424242" not in text


def test_scope_and_disallowed_resource_attributes_dropped_on_every_signal(
    collector: Collector,
) -> None:
    url, out = collector
    # Keys that are allowed elsewhere (log attributes, metric labels) but not on the resource.
    resource = {"attributes": _attrs(**{
        "service.name": "fitwise-backend", "user_hash": "QA-RES-UH", "route": "QA-RES-ROUTE",
        "telemetry.sdk.name": "QA-RES-SDK", "user.email": EMAIL,
    })}  # fmt: skip
    scope_attrs = _attrs(note="QA-SCOPE-NOTE", **{"user.email": EMAIL})
    scope = {"name": "qa-scope", "attributes": scope_attrs}
    span = {
        "traceId": "0123456789abcdef0123456789abcdee",
        "spanId": "0123456789abcdee",
        "name": "qa-res-span",
    }
    point = {"asInt": "1", "timeUnixNano": "1700000000000000000"}
    metric = {
        "name": "qa_res_metric",
        "sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": [point]},
    }
    spans = {"scope": scope, "spans": [span]}
    metrics = {"scope": scope, "metrics": [metric]}
    _post(url, "/v1/logs", _logs(resource, [{"body": {"stringValue": "qa-res-log"}}], scope))
    _post(url, "/v1/traces", {"resourceSpans": [{"resource": resource, "scopeSpans": [spans]}]})
    _post(
        url,
        "/v1/metrics",
        {"resourceMetrics": [{"resource": resource, "scopeMetrics": [metrics]}]},
    )
    markers = (("logs", "qa-res-log"), ("traces", "qa-res-span"), ("metrics", "qa_res_metric"))
    for signal, marker in markers:
        text = _read(out, signal, marker)
        line = next(json.loads(x) for x in text.splitlines() if marker in x)
        for rs in line[TOP[signal]]:
            keys = {a["key"] for a in rs["resource"]["attributes"]}
            assert keys <= RESOURCE_KEYS, (signal, keys)
        for leak in ("QA-RES-", "QA-SCOPE-NOTE", EMAIL):
            assert leak not in text, (signal, leak)


@pytest.mark.xfail(strict=True, reason="#151: scope name is not gated")
def test_scope_name_does_not_carry_pii(collector: Collector) -> None:
    url, out = collector
    scope = {"name": f"qa-scope-{EMAIL}"}
    _post(url, "/v1/logs", _logs({}, [{"body": {"stringValue": "qa-scope-name"}}], scope))
    assert EMAIL not in _read(out, "logs", "qa-scope-name")


@pytest.mark.xfail(strict=True, reason="#151: severity_text / event_name are not gated")
def test_severity_text_and_event_name_do_not_carry_pii(collector: Collector) -> None:
    url, out = collector
    rec = {"body": {"stringValue": "qa-sev"}, "severityText": f"SEV {EMAIL}", "eventName": EMAIL}
    _post(url, "/v1/logs", _logs({}, [rec]))
    assert EMAIL not in _read(out, "logs", "qa-sev")


@pytest.mark.xfail(strict=True, reason="#151: keep_keys keeps non-string values of allowed keys")
def test_allowed_attribute_with_map_value_does_not_carry_pii(collector: Collector) -> None:
    url, out = collector
    route = {"kvlistValue": {"values": [{"key": "x", "value": {"stringValue": EMAIL}}]}}
    rec = {"body": {"stringValue": "qa-attrmap"}, "attributes": [{"key": "route", "value": route}]}
    _post(url, "/v1/logs", _logs({}, [rec]))
    assert EMAIL not in _read(out, "logs", "qa-attrmap")


@pytest.mark.xfail(strict=True, reason="#151: allowed resource keys keep any value")
def test_allowed_resource_key_with_pii_value_is_not_exported(collector: Collector) -> None:
    url, out = collector
    resource = {"attributes": _attrs(**{"service.name": EMAIL})}
    _post(url, "/v1/logs", _logs(resource, [{"body": {"stringValue": "qa-svc"}}]))
    assert EMAIL not in _read(out, "logs", "qa-svc")
