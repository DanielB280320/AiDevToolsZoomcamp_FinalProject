"""The collector's privacy gate mirrors the app's allow-lists (spec §6.5, CLAUDE.md rule 6; #17).

`observability/collector/config.yaml` filters logs, spans and metrics a second time, independently
of the backend. These tests fail when the two drift apart, e.g. a field added to
`LOG_EVENT_FIELDS` but not to the collector (it would silently disappear from Loki) or a name
added to the collector only (it would let through what the app never meant to emit).
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.telemetry.privacy import (
    LOG_BASE_FIELDS,
    LOG_EVENT_FIELDS,
    METRIC_ATTRIBUTES,
    SENSITIVE_FIELD_NAMES,
    SPAN_ATTRIBUTE_PREFIX,
    SPAN_ATTRIBUTES,
)

CONFIG = Path(__file__).resolve().parents[3] / "observability" / "collector" / "config.yaml"

# Base fields that become part of the record (time, severity, body, trace context) rather than
# attributes; the other base fields are kept as attributes under these names.
BASE_FIELD_ATTRIBUTES = {"service": "service.name", "version": "service.version", "env": "env"}
RECORD_FIELDS = {"timestamp", "level", "message", "trace_id", "span_id"}
# `revision` is added to LOG_EVENT_FIELDS by #89 (migration step), which merges around the same
# time as this file; the collector already lets it through. Empty this set once #89 is merged.
COLLECTOR_AHEAD_OF_APP: frozenset[str] = frozenset({"revision"}) - LOG_EVENT_FIELDS


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return loaded


def _statements(config: dict[str, Any], processor: str, key: str) -> list[str]:
    groups = config["processors"][processor][key]
    return [statement for group in groups for statement in group["statements"]]


def _string_list(statement: str) -> set[str]:
    inner = re.search(r"\[(.*)\]\)$", statement)
    assert inner, statement
    return set(re.findall(r'"([^"]+)"', inner.group(1)))


def _alternation(statement: str) -> set[str]:
    """Names in `^(?:a\\.b|c|...)$` / `^prefix\\.(?:.+\\.)?(?:a|b)$`, regex escapes undone."""
    pattern = re.search(r'"(\^.*\$)"\)$', statement)
    assert pattern, statement
    groups = re.findall(r"\(\?:([^()]*)\)", pattern.group(1).replace("\\\\", "\\"))
    names = groups[-1].split("|")
    return {name.replace("\\.", ".") for name in names}


def _span_pattern(config: dict[str, Any]) -> re.Pattern[str]:
    statement = next(
        s
        for s in _statements(config, "transform/traces", "trace_statements")
        if s.startswith("keep_matching_keys(span.attributes")
    )
    raw = re.search(r'"(\^.*\$)"\)$', statement)
    assert raw
    return re.compile(raw.group(1).replace("\\\\", "\\"))


def test_log_event_fields_match_the_app(config: dict[str, Any]) -> None:
    statements = _statements(config, "transform/logs", "log_statements")
    copy = re.compile(r'^set\(log\.attributes\["([^"]+)"\], log\.cache\["\1"\]\)', re.M)
    copied = set(copy.findall("\n".join(statements)))
    event_fields = copied - {"logger"} - set(BASE_FIELD_ATTRIBUTES.values())
    assert event_fields >= LOG_EVENT_FIELDS, "fields the app logs that the collector would drop"
    assert event_fields - LOG_EVENT_FIELDS <= COLLECTOR_AHEAD_OF_APP, (
        "fields the collector lets through that the app's allow-list does not have"
    )

    keep = next(s for s in statements if s.startswith("keep_keys(log.attributes"))
    assert _string_list(keep) == copied | set(BASE_FIELD_ATTRIBUTES.values())


def test_log_statements_read_only_allow_listed_fields(config: dict[str, Any]) -> None:
    statements = "\n".join(_statements(config, "transform/logs", "log_statements"))
    read = set(re.findall(r'log\.cache\["([^"]+)"\]', statements))
    assert read <= set(LOG_BASE_FIELDS) | LOG_EVENT_FIELDS | COLLECTOR_AHEAD_OF_APP
    assert read >= set(LOG_BASE_FIELDS), "every base field is mapped"
    assert set(LOG_BASE_FIELDS) == RECORD_FIELDS | set(BASE_FIELD_ATTRIBUTES) | {"logger"}


def test_log_body_becomes_the_message_only(config: dict[str, Any]) -> None:
    statements = _statements(config, "transform/logs", "log_statements")
    body_sets = [s for s in statements if s.startswith("set(log.body")]
    assert body_sets == [
        'set(log.body, "")',
        'set(log.body, log.cache["message"]) where IsString(log.cache["message"])',
    ]
    assert statements[-2:] == body_sets, "the body is replaced last, after every field is copied"


def test_unparsed_lines_are_dropped_before_export(config: dict[str, Any]) -> None:
    pipeline = config["service"]["pipelines"]["logs"]
    assert pipeline["receivers"] == ["fluent_forward"]
    processors = pipeline["processors"]
    assert processors.index("transform/logs") < processors.index("filter/unparsed_logs")
    conditions = config["processors"]["filter/unparsed_logs"]["logs"]["log_record"]
    assert conditions == ['log.attributes["service.name"] == nil']


def test_span_attributes_match_the_app(config: dict[str, Any]) -> None:
    statement = next(
        s
        for s in _statements(config, "transform/traces", "trace_statements")
        if s.startswith("keep_matching_keys(span.attributes")
    )
    names = _alternation(statement)
    assert names == set(SPAN_ATTRIBUTES) | {f"{SPAN_ATTRIBUTE_PREFIX}.+"}


@pytest.mark.parametrize("key", [*sorted(SPAN_ATTRIBUTES), "fitwise.engine.rule"])
def test_allowed_span_attributes_pass(config: dict[str, Any], key: str) -> None:
    assert _span_pattern(config).fullmatch(key)


@pytest.mark.parametrize(
    "key",
    [
        "http.target",
        "http.user_agent",
        "user_agent.original",
        "url.query",
        "url.path",
        "client.address",
        "http.client_ip",
        "enduser.id",
        "http.request.header.authorization",
        "db.statement.parameters",
        "exception.message",
        "exception.stacktrace",
        "fitwise",
    ],
)
def test_other_span_attributes_are_dropped(config: dict[str, Any], key: str) -> None:
    assert not _span_pattern(config).fullmatch(key)


def test_sensitive_fitwise_span_keys_match_the_app(config: dict[str, Any]) -> None:
    statement = next(
        s
        for s in _statements(config, "transform/traces", "trace_statements")
        if s.startswith("delete_matching_keys(span.attributes")
    )
    assert _alternation(statement) == set(SENSITIVE_FIELD_NAMES)


def test_metric_labels_match_the_app(config: dict[str, Any]) -> None:
    statements = _statements(config, "transform/metrics", "metric_statements")
    keep = next(s for s in statements if s.startswith("keep_keys(datapoint.attributes"))
    assert _string_list(keep) == set(METRIC_ATTRIBUTES)


def test_every_pipeline_passes_its_privacy_processor(config: dict[str, Any]) -> None:
    pipelines = config["service"]["pipelines"]
    assert "transform/traces" in pipelines["traces"]["processors"]
    assert "transform/metrics" in pipelines["metrics"]["processors"]
    assert "transform/logs" in pipelines["logs"]["processors"]
    # `env` is inserted only when missing, never overwritten.
    for name in ("traces", "metrics", "logs"):
        assert "resource/env" in pipelines[name]["processors"]
    assert config["processors"]["resource/env"]["attributes"] == [
        {"key": "env", "value": "${env:FITWISE_ENV}", "action": "insert"}
    ]
