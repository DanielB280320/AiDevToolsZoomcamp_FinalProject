"""Feature-flag allow-list, validation and the reader's fallbacks (no database needed)."""

import datetime as dt

import pytest
from fastapi import FastAPI
from hypothesis import given
from hypothesis import strategies as st

from app.config import (
    FAULT_INJECTION_LATENCY_MS_MAX,
    FEATURE_FLAGS,
    FLAG_CACHE_TTL_SECONDS,
)
from app.services.flags import (
    DEFAULT_FLAGS,
    FlagError,
    FlagReader,
    FlagValues,
    effective_value,
    normalize_value,
    validate_actor,
    validate_change,
)
from app.telemetry.privacy import LOG_EVENT_FIELDS, SENSITIVE_FIELD_NAMES
from tests.conftest import JsonLogs
from tests.fakes import FakeClock

NOW = dt.datetime(2026, 10, 22, 9, 0, tzinfo=dt.UTC)


def test_the_allow_list_is_exactly_the_spec_flags_with_their_defaults() -> None:
    assert {key: spec.default for key, spec in FEATURE_FLAGS.items()} == {
        "progression_engine": "v1",
        "off_search_enabled": "true",
        "fault_injection_latency_ms": "0",
    }
    assert FEATURE_FLAGS["progression_engine"].choices == ("v1", "v2")
    assert FEATURE_FLAGS["off_search_enabled"].choices == ("true", "false")
    assert FEATURE_FLAGS["fault_injection_latency_ms"].int_max == FAULT_INJECTION_LATENCY_MS_MAX


def test_meal_planner_is_not_a_flag_until_the_spec_has_it() -> None:
    assert "meal_planner" not in FEATURE_FLAGS
    with pytest.raises(FlagError, match="unknown flag"):
        normalize_value("meal_planner", "true")


def test_latency_bound_is_above_the_alert_threshold_and_the_ttl_meets_the_10s_target() -> None:
    assert 1_000 < FAULT_INJECTION_LATENCY_MS_MAX <= 30_000  # p95 > 1 s alert (§15.1)
    assert 0 < FLAG_CACHE_TTL_SECONDS < 10


def test_defaults_typed() -> None:
    expected = FlagValues(
        progression_engine="v1", off_search_enabled=True, fault_injection_latency_ms=0
    )
    assert expected == DEFAULT_FLAGS


@pytest.mark.parametrize(
    ("key", "raw", "stored"),
    [
        ("progression_engine", "v1", "v1"),
        ("progression_engine", "v2", "v2"),
        ("off_search_enabled", "true", "true"),
        ("off_search_enabled", "false", "false"),
        ("fault_injection_latency_ms", "0", "0"),
        ("fault_injection_latency_ms", "1500", "1500"),
        ("fault_injection_latency_ms", "007", "7"),
        ("fault_injection_latency_ms", str(FAULT_INJECTION_LATENCY_MS_MAX), "10000"),
    ],
)
def test_valid_values_are_normalized(key: str, raw: str, stored: str) -> None:
    assert normalize_value(key, raw) == stored


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("progression_engine", "v3"),
        ("progression_engine", "V1"),
        ("progression_engine", ""),
        ("progression_engine", " v1"),
        ("off_search_enabled", "TRUE"),
        ("off_search_enabled", "yes"),
        ("off_search_enabled", "1"),
        ("fault_injection_latency_ms", "-1"),
        ("fault_injection_latency_ms", "+5"),
        ("fault_injection_latency_ms", "1.5"),
        ("fault_injection_latency_ms", "1e3"),
        ("fault_injection_latency_ms", " 5"),
        ("fault_injection_latency_ms", ""),
        ("fault_injection_latency_ms", "abc"),
        ("fault_injection_latency_ms", str(FAULT_INJECTION_LATENCY_MS_MAX + 1)),
        ("fault_injection_latency_ms", "٣"),  # a non-ASCII digit
    ],
)
def test_invalid_values_are_rejected(key: str, raw: str) -> None:
    with pytest.raises(FlagError, match=f"invalid value for {key}"):
        normalize_value(key, raw)


@given(st.integers(min_value=0, max_value=FAULT_INJECTION_LATENCY_MS_MAX))
def test_property_every_latency_in_range_round_trips(ms: int) -> None:
    assert normalize_value("fault_injection_latency_ms", str(ms)) == str(ms)
    stored = normalize_value("fault_injection_latency_ms", str(ms))
    values = FlagValues.from_stored({"fault_injection_latency_ms": stored})
    assert values.fault_injection_latency_ms == ms


@given(
    st.one_of(
        st.integers(max_value=-1),
        st.integers(min_value=FAULT_INJECTION_LATENCY_MS_MAX + 1),
    )
)
def test_property_every_latency_out_of_range_is_rejected(ms: int) -> None:
    with pytest.raises(FlagError):
        normalize_value("fault_injection_latency_ms", str(ms))


@given(st.text(max_size=12).filter(lambda s: s not in ("v1", "v2")))
def test_property_unknown_progression_engine_reads_as_v1(stored: str) -> None:
    """F11.5: unknown engine versions fall back to v1."""
    assert effective_value("progression_engine", stored) == "v1"
    assert FlagValues.from_stored({"progression_engine": stored}).progression_engine == "v1"


@pytest.mark.parametrize(
    ("key", "stored", "effective"),
    [
        ("progression_engine", None, "v1"),
        ("off_search_enabled", None, "true"),
        ("fault_injection_latency_ms", None, "0"),
        ("off_search_enabled", "maybe", "true"),
        ("fault_injection_latency_ms", "-20", "0"),
        ("fault_injection_latency_ms", "999999", "0"),
        ("progression_engine", "v2", "v2"),
    ],
)
def test_missing_or_invalid_stored_values_read_as_the_default(
    key: str, stored: str | None, effective: str
) -> None:
    assert effective_value(key, stored) == effective


def test_rows_for_unknown_keys_are_ignored() -> None:
    assert FlagValues.from_stored({"meal_planner": "true", "x": "y"}) == DEFAULT_FLAGS


@pytest.mark.parametrize("actor", ["oncall-agent", "owner", "devops-agent", "qa2"])
def test_actor_labels_are_accepted(actor: str) -> None:
    assert validate_actor(actor) == actor


@pytest.mark.parametrize(
    "actor",
    ["", "ana@x.test", "Ana", "Ana Lopez", "owner.", "-owner", "owner-", "on--call", "a" * 33],
)
def test_actor_that_could_be_an_email_or_a_name_is_rejected(actor: str) -> None:
    with pytest.raises(FlagError, match="invalid actor"):
        validate_actor(actor)


def test_validate_change_checks_key_first() -> None:
    with pytest.raises(FlagError, match="unknown flag 'nope'; allowed flags: "):
        validate_change("nope", "v1", "owner")


def test_reader_with_unreachable_database_uses_defaults_and_logs_type_only(
    offline_app: FastAPI, json_logs: JsonLogs
) -> None:
    reader: FlagReader = offline_app.state.flags
    assert reader.values() == DEFAULT_FLAGS

    [line] = json_logs.with_message("feature flags unavailable")
    assert line["error_type"] == "OperationalError"
    assert line["outcome"] == "kept_previous"
    assert "postgresql" not in json_logs.text and "unused" not in json_logs.text


def test_reader_retries_an_unavailable_database_only_after_the_ttl(
    offline_app: FastAPI, json_logs: JsonLogs
) -> None:
    clock = FakeClock(NOW)
    offline_app.state.clock = clock  # the reader reads the clock through app.state
    reader: FlagReader = offline_app.state.flags

    reader.values()
    clock.advance(seconds=FLAG_CACHE_TTL_SECONDS - 0.1)
    reader.values()
    assert len(json_logs.with_message("feature flags unavailable")) == 1
    clock.advance(seconds=0.1)
    reader.values()
    assert len(json_logs.with_message("feature flags unavailable")) == 2


def test_new_log_fields_are_not_sensitive_names() -> None:
    new = {"flag_key", "flag_old_value", "flag_new_value", "actor"}
    assert new <= LOG_EVENT_FIELDS
    assert not new & SENSITIVE_FIELD_NAMES
