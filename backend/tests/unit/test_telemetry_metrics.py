"""§14 metric instruments (issue #16): registered at startup, closed label sets."""

from fastapi.testclient import TestClient

from app.telemetry.metrics import COUNTER_NAMES, RULES_BY_KIND
from app.telemetry.privacy import METRIC_ATTRIBUTES
from tests.conftest import Captured


def _values(captured: Captured, name: str) -> dict[tuple[tuple[str, object], ...], float]:
    return {
        tuple(sorted(dict(point.attributes).items())): point.value
        for point in captured.metric_points(name)
    }


def test_all_custom_instruments_exist_at_startup_with_zero_series(captured: Captured) -> None:
    names = captured.metric_names()

    assert set(COUNTER_NAMES) <= names
    for name in (
        "fitwise_sets_logged_total",
        "fitwise_meal_checkoffs_total",
        "fitwise_workouts_finished_total",
    ):
        assert _values(captured, name) == {(): 0}
    generated = _values(captured, "fitwise_suggestions_generated_total")
    assert set(generated.values()) == {0}
    assert (("kind", "progression"), ("rule", "double")) in generated
    assert (("kind", "calories"), ("rule", "adaptive_calories")) in generated
    assert len(generated) == sum(len(rules) for rules in RULES_BY_KIND.values())
    decided = _values(captured, "fitwise_suggestions_decided_total")
    assert len(decided) == 6
    assert set(decided.values()) == {0}
    assert set(_values(captured, "fitwise_off_search_total")) == {
        (("outcome", outcome),) for outcome in ("ok", "error", "timeout", "disabled")
    }


def test_recording_methods_increment_the_right_series(captured: Captured) -> None:
    metrics = captured.telemetry.metrics
    metrics.set_logged()
    metrics.set_logged()
    metrics.meal_checked_off()
    metrics.workout_finished()
    metrics.suggestion_generated("progression", "linear")
    metrics.suggestion_decided("progression", "accepted")
    metrics.off_search("timeout")

    assert _values(captured, "fitwise_sets_logged_total") == {(): 2}
    assert _values(captured, "fitwise_meal_checkoffs_total") == {(): 1}
    assert _values(captured, "fitwise_workouts_finished_total") == {(): 1}
    generated = _values(captured, "fitwise_suggestions_generated_total")
    assert generated[(("kind", "progression"), ("rule", "linear"))] == 1
    decided = _values(captured, "fitwise_suggestions_decided_total")
    assert decided[(("decision", "accepted"), ("kind", "progression"))] == 1
    assert _values(captured, "fitwise_off_search_total")[(("outcome", "timeout"),)] == 1


def test_labels_outside_the_allow_list_are_dropped_from_every_instrument(
    captured: Captured,
) -> None:
    meter = captured.telemetry.meter_provider.get_meter("test")
    counter = meter.create_counter("test_counter_total")
    counter.add(1, {"outcome": "ok", "email": "ann@example.com", "weight_kg": 84.2})

    [point] = captured.metric_points("test_counter_total")
    assert dict(point.attributes) == {"outcome": "ok"}


def test_every_exported_label_is_allow_listed(captured: Captured) -> None:
    with TestClient(captured.app) as client:
        client.get("/api/v1/healthz")
        client.get("/api/v1/readyz")
        client.get("/api/v1/nope?q=lasagne")
        client.request("BREW", "/api/v1/healthz")

    data = captured.metric_reader.get_metrics_data()
    assert data is not None
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                for point in metric.data.data_points:
                    assert set(point.attributes or {}) <= METRIC_ATTRIBUTES, metric.name
                    assert "lasagne" not in str(point.attributes)
    methods = {dict(p.attributes)["method"] for p in captured.metric_points("http_server_duration")}
    assert methods == {"GET", "_OTHER"}
