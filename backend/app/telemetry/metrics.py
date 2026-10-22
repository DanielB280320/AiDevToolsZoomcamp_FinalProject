"""FitWise metric instruments (spec §14 Metrics).

All instruments are created at startup. Label values are closed sets (typed `Literal`s from
openapi.yaml), so no user data and no unbounded cardinality can reach Prometheus. Every known
series is initialised to 0 so `rate()`/`increase()` see the first event.

Prometheus names after the collector's OTLP → Prometheus translation:
`http_server_duration_seconds_{bucket,sum,count}{route,method,status}`,
`fitwise_sets_logged_total`, `fitwise_meal_checkoffs_total`, `fitwise_workouts_finished_total`,
`fitwise_suggestions_generated_total{kind,rule}`,
`fitwise_suggestions_decided_total{kind,decision}`, `fitwise_off_search_total{outcome}`.
Resource attributes add `env`, `service_name`.
"""

from typing import Final, Literal, get_args

from opentelemetry.metrics import Meter

SuggestionKind = Literal["progression", "calories", "recalc"]
SuggestionRule = Literal[
    "linear",
    "double",
    "deload",
    "bodyweight",
    "timed",
    "calibration",
    "adaptive_calories",
    "weight_change",
]
SuggestionDecision = Literal["accepted", "rejected"]
OffSearchOutcome = Literal["ok", "error", "timeout", "disabled"]

# Which rules each suggestion kind can come from (F11, F14).
RULES_BY_KIND: Final[dict[SuggestionKind, tuple[SuggestionRule, ...]]] = {
    "progression": ("linear", "double", "deload", "bodyweight", "timed", "calibration"),
    "calories": ("adaptive_calories",),
    "recalc": ("weight_change",),
}

HTTP_SERVER_DURATION: Final = "http_server_duration"
COUNTER_NAMES: Final = (
    "fitwise_sets_logged_total",
    "fitwise_meal_checkoffs_total",
    "fitwise_workouts_finished_total",
    "fitwise_suggestions_generated_total",
    "fitwise_suggestions_decided_total",
    "fitwise_off_search_total",
)
# Seconds; covers the 500 ms SLO and the 1 s alert threshold (spec §6.6, §15.1).
DURATION_BUCKETS_SECONDS: Final = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    10.0,
)
HTTP_METHODS: Final = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
)
UNMATCHED_ROUTE: Final = "unmatched"


def normalize_method(method: str) -> str:
    """A standard HTTP method, or `_OTHER` (a client-chosen string never becomes a label)."""
    return method if method in HTTP_METHODS else "_OTHER"


class FitwiseMetrics:
    def __init__(self, meter: Meter) -> None:
        self.http_server_duration = meter.create_histogram(
            HTTP_SERVER_DURATION,
            unit="s",
            description="Duration of HTTP requests by route template, method and status.",
            explicit_bucket_boundaries_advisory=list(DURATION_BUCKETS_SECONDS),
        )
        self._sets_logged = meter.create_counter(
            "fitwise_sets_logged_total", description="Sets logged (created or replaced)."
        )
        self._meal_checkoffs = meter.create_counter(
            "fitwise_meal_checkoffs_total", description="Planned meals checked off."
        )
        self._workouts_finished = meter.create_counter(
            "fitwise_workouts_finished_total", description="Workouts finished."
        )
        self._suggestions_generated = meter.create_counter(
            "fitwise_suggestions_generated_total",
            description="Suggestions generated, by kind and rule.",
        )
        self._suggestions_decided = meter.create_counter(
            "fitwise_suggestions_decided_total",
            description="Suggestions accepted or rejected, by kind.",
        )
        self._off_search = meter.create_counter(
            "fitwise_off_search_total", description="Open Food Facts searches, by outcome."
        )
        self._initialise_series()

    def _initialise_series(self) -> None:
        self._sets_logged.add(0)
        self._meal_checkoffs.add(0)
        self._workouts_finished.add(0)
        for kind, rules in RULES_BY_KIND.items():
            for rule in rules:
                self._suggestions_generated.add(0, {"kind": kind, "rule": rule})
            for decision in get_args(SuggestionDecision):
                self._suggestions_decided.add(0, {"kind": kind, "decision": decision})
        for outcome in get_args(OffSearchOutcome):
            self._off_search.add(0, {"outcome": outcome})

    def record_request(
        self, *, route: str | None, method: str, status: int, seconds: float
    ) -> None:
        self.http_server_duration.record(
            seconds,
            {
                "route": route or UNMATCHED_ROUTE,
                "method": normalize_method(method),
                "status": status,
            },
        )

    def set_logged(self) -> None:
        self._sets_logged.add(1)

    def meal_checked_off(self) -> None:
        self._meal_checkoffs.add(1)

    def workout_finished(self) -> None:
        self._workouts_finished.add(1)

    def suggestion_generated(self, kind: SuggestionKind, rule: SuggestionRule) -> None:
        self._suggestions_generated.add(1, {"kind": kind, "rule": rule})

    def suggestion_decided(self, kind: SuggestionKind, decision: SuggestionDecision) -> None:
        self._suggestions_decided.add(1, {"kind": kind, "decision": decision})

    def off_search(self, outcome: OffSearchOutcome) -> None:
        self._off_search.add(1, {"outcome": outcome})
