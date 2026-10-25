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

from app.telemetry import privacy
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
# Fields the collector lets through before the app logs them (none at the moment).
COLLECTOR_AHEAD_OF_APP: frozenset[str] = frozenset()


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
    assert body_sets[:2] == [
        'set(log.body, "")',
        'set(log.body, log.cache["message"]) where IsString(log.cache["message"])',
    ]
    last = statements.index(body_sets[1])
    assert statements.index(body_sets[0]) == last - 1, "the body is replaced after every field"
    assert all("log.body" not in s for s in statements[: last - 1] if "ParseJSON" not in s)


def test_log_message_is_scrubbed_like_the_app(config: dict[str, Any]) -> None:
    statements = _statements(config, "transform/logs", "log_statements")
    last = statements.index(
        'set(log.body, log.cache["message"]) where IsString(log.cache["message"])'
    )
    after = statements[last + 1 :]
    patterns = [(re.search(r'replace_pattern\(log\.body, "(.*)", "(.*)"\)$', s), s) for s in after]
    found = [(m.group(1).replace("\\\\", "\\"), m.group(2)) for m, _ in patterns if m]
    assert found == [
        (privacy._EMAIL.pattern, "[email]"),
        (privacy._BEARER.pattern, "Bearer [token]"),
        (privacy._JWT.pattern, "[token]"),
    ]
    cap = after[len(found)]
    assert f"Substring(log.body, 0, {privacy.MAX_STRING_LENGTH})" in cap
    assert f"Len(log.body) > {privacy.MAX_STRING_LENGTH}" in cap


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


# --- dev -> prod forwarding (#67) ----------------------------------------------------------


def test_forwarded_logs_get_the_same_attribute_allow_list(config: dict[str, Any]) -> None:
    """Prod re-applies the log attribute allow-list to logs that arrive from the dev collector."""
    forwarded = _statements(config, "transform/forwarded_logs", "log_statements")
    keep = next(s for s in forwarded if s.startswith("keep_keys(log.attributes"))
    main = _statements(config, "transform/logs", "log_statements")
    main_keep = next(s for s in main if s.startswith("keep_keys(log.attributes"))
    assert _string_list(keep) == _string_list(main_keep)
    assert any(s.startswith("replace_pattern(log.body") and "[email]" in s for s in forwarded)
    pipeline = config["service"]["pipelines"]["logs/forwarded"]
    assert pipeline["receivers"] == ["otlp"]
    assert "transform/forwarded_logs" in pipeline["processors"]
    assert "resource/env" in pipeline["processors"]


def test_forward_overlay_only_swaps_exporters() -> None:
    """The dev overlay keeps every gate of config.yaml and only changes where data goes."""
    forward = yaml.safe_load(CONFIG.with_name("config.forward.yaml").read_text(encoding="utf-8"))
    assert set(forward) == {"exporters", "service"}
    assert set(forward["service"]) == {"pipelines"}
    base = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert set(forward["service"]["pipelines"]) == {"traces", "metrics", "logs"}
    for name, pipeline in forward["service"]["pipelines"].items():
        assert set(pipeline) == {"exporters"}, name
        assert pipeline["exporters"] == ["otlp_grpc/upstream"]
        assert name in base["service"]["pipelines"]
    upstream = forward["exporters"]["otlp_grpc/upstream"]
    assert upstream["endpoint"] == "${env:OTLP_UPSTREAM_ENDPOINT}"
