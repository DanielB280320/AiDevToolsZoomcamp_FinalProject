"""The allow-listed JSON logger (issue #16, spec §6.5, CLAUDE.md rule 6)."""

import io
import json
import logging
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from opentelemetry.sdk.trace import TracerProvider

from app.telemetry import configure_logging, get_logger
from app.telemetry.logs import (
    JsonFormatter,
    RequestContext,
    reset_request_context,
    set_request_context,
)
from app.telemetry.privacy import LOG_BASE_FIELDS, LOG_EVENT_FIELDS, SENSITIVE_FIELD_NAMES
from tests.conftest import JsonLogs

ALLOWED_KEYS = set(LOG_BASE_FIELDS) | LOG_EVENT_FIELDS

# The issue's list of sensitive fields, each with a value that is unique in the output.
FORBIDDEN_FIELDS: dict[str, Any] = {
    "email": "ann.athlete@example.com",
    "display_name": "Ann Athlete",
    "name": "Annabel Secretname",
    "password": "hunter2-correct-horse",
    "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
    "cookie": "fitwise_session=s3cr3t-cookie-value",
    "weight_kg": 84.2371,
    "height_cm": 181.4372,
    "body_fat_pct": 17.3373,
    "neck_cm": 38.4374,
    "waist_cm": 86.5375,
    "hip_cm": 99.6376,
    "food_name": "Grandma's lasagne",
    "note": "felt dizzy after the third set",
}


def _value_text(value: Any) -> str:
    return value if isinstance(value, str) else repr(value)


def test_every_line_has_the_base_fields_and_is_json(json_logs: JsonLogs) -> None:
    get_logger("app.test").info("hello", outcome="ok")

    [line] = json_logs.lines()
    for key in ("timestamp", "level", "message", "trace_id", "span_id", "env"):
        assert key in line
    assert line["message"] == "hello"
    assert line["level"] == "info"
    assert line["env"] == "test"
    assert line["outcome"] == "ok"
    assert line["timestamp"].endswith("Z")
    assert set(line) <= ALLOWED_KEYS


def test_lines_inside_a_span_carry_its_trace_and_span_id(json_logs: JsonLogs) -> None:
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        get_logger("app.test").info("inside")
    context = span.get_span_context()

    [line] = json_logs.lines()
    assert line["trace_id"] == format(context.trace_id, "032x")
    assert line["span_id"] == format(context.span_id, "016x")


def test_route_and_user_hash_come_from_the_request_context(json_logs: JsonLogs) -> None:
    context = RequestContext(route="/api/v1/x/{id}", method="GET", hash_user=lambda _: "abc123")
    token = set_request_context(context)
    try:
        get_logger("app.test").info("anonymous")
        context.user_hash = "abc123"
        get_logger("app.test").info("signed in")
    finally:
        reset_request_context(token)

    anonymous, signed_in = json_logs.lines()
    assert anonymous["route"] == "/api/v1/x/{id}"
    assert "user_hash" not in anonymous
    assert signed_in["user_hash"] == "abc123"


def test_sensitive_fields_never_reach_the_output(json_logs: JsonLogs) -> None:
    get_logger("app.test").warning("profile updated", **FORBIDDEN_FIELDS)

    text = json_logs.text
    for key, value in FORBIDDEN_FIELDS.items():
        assert _value_text(value) not in text, f"value of {key!r} leaked"
        assert f'"{key}"' not in text, f"key {key!r} leaked"
    [line] = json_logs.lines()
    assert set(line) <= ALLOWED_KEYS


@pytest.mark.parametrize(("key", "value"), FORBIDDEN_FIELDS.items(), ids=FORBIDDEN_FIELDS)
def test_each_sensitive_field_is_dropped_on_its_own(
    json_logs: JsonLogs, key: str, value: Any
) -> None:
    get_logger("app.test").info("event", **{key: value})
    # The stdlib path (third-party code, `extra=`) is filtered by the formatter too.
    logging.getLogger("app.test").info("event", extra={key: value} if key != "name" else {})

    assert _value_text(value) not in json_logs.text


def test_every_sensitive_name_from_the_privacy_module_is_outside_the_allow_list() -> None:
    assert not SENSITIVE_FIELD_NAMES & LOG_EVENT_FIELDS
    assert set(FORBIDDEN_FIELDS) <= SENSITIVE_FIELD_NAMES


_keys = st.text(st.characters(categories=["L", "N"], include_characters="_."), min_size=1)
_secret_values = st.text(min_size=1, max_size=40).map(lambda text: f"zz-secret-{text}")


@settings(max_examples=200, deadline=None)
@given(fields=st.dictionaries(_keys.filter(lambda k: k not in LOG_EVENT_FIELDS), _secret_values))
def test_property_unknown_fields_are_always_dropped(fields: dict[str, str]) -> None:
    stream = io.StringIO()
    logger = _isolated_logger(stream)
    logger.info("event", **fields)

    output = stream.getvalue()
    assert "zz-secret-" not in output
    assert set(json.loads(output)) <= ALLOWED_KEYS


@settings(max_examples=200, deadline=None)
@given(
    fields=st.dictionaries(
        st.sampled_from(sorted(LOG_EVENT_FIELDS)),
        st.one_of(
            st.dictionaries(st.text(max_size=5), _secret_values, min_size=1),
            st.lists(_secret_values, min_size=1),
            st.tuples(_secret_values),
        ),
    )
)
def test_property_structured_values_are_dropped_even_for_allowed_keys(
    fields: dict[str, Any],
) -> None:
    stream = io.StringIO()
    _isolated_logger(stream).info("event", **fields)

    assert "zz-secret-" not in stream.getvalue()


@settings(max_examples=100, deadline=None)
@given(args=st.lists(_secret_values, min_size=1, max_size=3))
def test_property_percent_arguments_are_never_interpolated(args: list[str]) -> None:
    stream = io.StringIO()
    logger = _isolated_logger(stream).logger
    logger.info(" ".join(["%s"] * len(args)), *args)

    assert "zz-secret-" not in stream.getvalue()


def test_emails_and_tokens_in_the_message_text_are_masked(json_logs: JsonLogs) -> None:
    get_logger("app.test").info(
        "login for ann.athlete@example.com with Bearer abc.def and eyJa.eyJb.sig"
    )

    [line] = json_logs.lines()
    assert "ann.athlete@example.com" not in line["message"]
    assert "abc.def" not in line["message"]
    assert "eyJa.eyJb.sig" not in line["message"]
    assert "[email]" in line["message"]


def test_exceptions_log_their_type_but_never_message_or_traceback(json_logs: JsonLogs) -> None:
    try:
        raise ValueError("weight 84.2371 for ann.athlete@example.com")
    except ValueError:
        logging.getLogger("app.test").exception("failed")

    [line] = json_logs.lines()
    assert line["error_type"] == "ValueError"
    assert "84.2371" not in json_logs.text
    assert "Traceback" not in json_logs.text


def test_non_string_messages_are_replaced_by_their_type(json_logs: JsonLogs) -> None:
    logging.getLogger("app.test").error(ValueError("note: felt dizzy"))

    [line] = json_logs.lines()
    assert line["message"] == "<ValueError>"
    assert "dizzy" not in json_logs.text


def test_configure_logging_writes_json_to_stdout_and_silences_uvicorn_access(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(level="INFO", env="dev", service="fitwise-backend", version="abc123")
    try:
        get_logger("app.test").info("to stdout", status=200)
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "1.2.3.4", "GET", "/api/v1/foods?q=lasagne", "1.1", 200
        )
        logging.getLogger("uvicorn.error").warning("uvicorn says %s", "zz-secret-arg")
    finally:
        _remove_json_handlers()

    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines()]
    assert [line["message"] for line in lines] == ["to stdout", "uvicorn says %s"]
    assert lines[0]["env"] == "dev"
    assert lines[0]["version"] == "abc123"
    assert lines[0]["service"] == "fitwise-backend"
    assert "lasagne" not in out
    assert "zz-secret-arg" not in out


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    before = len(root.handlers)
    try:
        configure_logging(level="INFO", env="test", service="s", version="v")
        configure_logging(level="INFO", env="test", service="s", version="v")
        assert len(root.handlers) == before + 1
    finally:
        _remove_json_handlers()


def _isolated_logger(stream: io.StringIO) -> Any:
    """A logger that writes only to `stream`, for Hypothesis examples (no fixtures)."""
    name = "fitwise.hypothesis"
    std = logging.getLogger(name)
    std.handlers.clear()
    std.propagate = False
    std.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(env="test", service="s", version="v"))
    std.addHandler(handler)
    return get_logger(name)


def _remove_json_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_fitwise_json_handler", False):
            root.removeHandler(handler)
