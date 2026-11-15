"""F15 chart engine: set outcomes, exercise history with PR markers, rolling weight average."""

import datetime as dt

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines import body_tracking
from app.engines import charts as e

D = dt.date(2026, 10, 1)


def v(**k: float | None) -> e.SetValues:
    return e.SetValues(**k)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("values", "flags", "status", "completion"),
    [
        (v(target_reps=8, target_weight_kg=50, reps=8, weight_kg=50), {}, "met", 1.0),
        (v(target_reps=8, target_weight_kg=50, reps=10, weight_kg=52.5), {}, "met", 1.0),
        (v(target_reps=8, target_weight_kg=50, reps=6, weight_kg=50), {}, "partial", 0.75),
        # reps reached but lighter than the target weight: partial, completion is reps-based
        (v(target_reps=8, target_weight_kg=50, reps=8, weight_kg=40), {}, "partial", 1.0),
        (v(target_reps=8, reps=8), {}, "met", 1.0),  # no target weight
        (v(target_reps=None, reps=5), {}, "met", None),  # nothing to compare with
        (v(target_seconds=600, seconds=300), {"timed": True}, "partial", 0.5),
        (v(target_seconds=600, seconds=900), {"timed": True}, "met", 1.0),
        (v(target_reps=8, target_weight_kg=50), {"logged": False}, "missed", 0.0),
        (v(target_reps=8, target_weight_kg=50), {"skipped": True}, "skipped", 0.0),
        (v(reps=5, weight_kg=20), {"extra": True}, "extra", None),
    ],
)
def test_set_outcome_table(
    values: e.SetValues, flags: dict[str, bool], status: str, completion: float | None
) -> None:
    args = {"logged": True, "skipped": False, "extra": False, "timed": False} | flags
    result = e.set_outcome(values, **args)
    assert result.status == status
    assert result.completion == completion
    assert result.reason


def mk_set(n: int, reps: int, kg: float, tr: int = 8, tkg: float = 50) -> e.LoggedSet:
    return e.LoggedSet(n, v(target_reps=tr, target_weight_kg=tkg, reps=reps, weight_kg=kg))


def test_history_top_set_volume_snapshot_and_prs() -> None:
    d = dt.timedelta
    sessions = [
        ("c", D + d(days=14), [mk_set(1, 8, 60, 8, 55)]),
        ("a", D, [mk_set(1, 8, 50), mk_set(2, 6, 50)]),
        ("b", D + d(days=7), [mk_set(1, 8, 50), mk_set(2, 8, 55)]),
    ]
    points = e.exercise_history(sessions, timed=False)
    assert [p.session_id for p in points] == ["a", "b", "c"]  # oldest first
    a, b, c = points
    assert (a.top_set_weight_kg, a.top_set_reps, a.volume_kg, a.is_pr) == (50, 8, 700.0, True)
    assert (b.top_set_weight_kg, b.volume_kg, b.is_pr) == (55, 840.0, True)
    assert (c.target_weight_kg, c.top_set_weight_kg, c.is_pr) == (55, 60, True)  # snapshot
    flat = e.exercise_history(
        [("a", D, [mk_set(1, 8, 50)]), ("b", D + d(days=1), [mk_set(1, 8, 50)])], timed=False
    )
    assert [p.is_pr for p in flat] == [True, False]  # equal is not a record
    assert e.exercise_history([("a", D, [])], timed=False) == []


def test_history_timed_and_bodyweight_rank() -> None:
    d = dt.timedelta
    timed = [
        ("a", D, [e.LoggedSet(1, v(target_seconds=60, seconds=50))]),
        ("b", D + d(days=1), [e.LoggedSet(1, v(target_seconds=60, seconds=70))]),
    ]
    points = e.exercise_history(timed, timed=True)
    assert [(p.top_set_seconds, p.is_pr) for p in points] == [(50, True), (70, True)]
    body = [
        ("a", D, [e.LoggedSet(1, v(reps=10))]),
        ("b", D + d(days=1), [e.LoggedSet(1, v(reps=12))]),
        ("c", D + d(days=2), [e.LoggedSet(1, v(reps=0, weight_kg=None, seconds=None))]),
    ]
    points = e.exercise_history(body, timed=False)
    assert [(p.top_set_reps, p.is_pr, p.volume_kg) for p in points] == [
        (10, True, 0.0),
        (12, True, 0.0),
        (0, False, 0.0),
    ]


def test_rolling_average_counts_only_existing_weigh_ins() -> None:
    w = [(D, 80.0), (D + dt.timedelta(days=2), 79.0), (D + dt.timedelta(days=10), 78.0)]
    days = [
        D - dt.timedelta(days=1),
        D,
        D + dt.timedelta(days=2),
        D + dt.timedelta(days=6),
        D + dt.timedelta(days=7),
        D + dt.timedelta(days=10),
    ]
    assert e.rolling_weight_average(w, days) == [None, 80.0, 79.5, 79.5, 79.0, 78.0]


@given(
    st.dictionaries(
        st.integers(0, 60).map(lambda n: D + dt.timedelta(days=n)),
        st.floats(40, 200),
        max_size=40,
    )
)
def test_rolling_average_matches_the_f14_engine(weights: dict[dt.date, float]) -> None:
    days = [D + dt.timedelta(days=n) for n in range(-3, 65)]
    got = e.rolling_weight_average(weights.items(), days)
    for day, value in zip(days, got, strict=True):
        expected = body_tracking.seven_day_average(weights.items(), day).average_kg
        assert (value is None) == (expected is None)
        if value is not None and expected is not None:
            assert value == pytest.approx(expected, abs=1e-6)


def test_mean_ratio_and_week_start() -> None:
    assert e.mean_ratio([]) is None
    assert e.mean_ratio([None, None]) is None
    assert e.mean_ratio([1.0, None, 0.5]) == 0.75
    assert e.week_start(dt.date(2026, 10, 25)) == dt.date(2026, 10, 19)  # Sunday
    assert e.week_start(dt.date(2026, 10, 19)) == dt.date(2026, 10, 19)


# ───────────── period overview (D109) ─────────────


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (dt.date(2026, 11, 9), dt.date(2026, 11, 15), (dt.date(2026, 11, 2), dt.date(2026, 11, 8))),
        (dt.date(2026, 11, 15), dt.date(2026, 11, 15), (dt.date(2026, 11, 14),) * 2),
        (
            dt.date(2026, 10, 17),
            dt.date(2026, 11, 15),
            (dt.date(2026, 9, 17), dt.date(2026, 10, 16)),
        ),
        (dt.date(2026, 3, 1), dt.date(2026, 3, 3), (dt.date(2026, 2, 26), dt.date(2026, 2, 28))),
        (dt.date(2024, 3, 1), dt.date(2024, 3, 2), (dt.date(2024, 2, 28), dt.date(2024, 2, 29))),
    ],
)
def test_previous_period_table(
    start: dt.date, end: dt.date, expected: tuple[dt.date, dt.date]
) -> None:
    assert e.previous_period(start, end) == expected


@given(
    start=st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 1, 1)),
    days=st.integers(min_value=1, max_value=371),
)
def test_previous_period_property(start: dt.date, days: int) -> None:
    end = start + dt.timedelta(days=days - 1)
    prev_start, prev_end = e.previous_period(start, end)
    assert prev_end == start - dt.timedelta(days=1)
    assert (prev_end - prev_start).days + 1 == days


@pytest.mark.parametrize(
    ("days", "kind"),
    [(1, "day"), (7, "day"), (30, "day"), (31, "day"), (32, "week"), (182, "week")],
)
def test_bucket_kind_table(days: int, kind: str) -> None:
    assert e.bucket_kind(days) == kind


def test_bucket_starts_table() -> None:
    thursday = dt.date(2026, 11, 12)
    assert e.bucket_starts(thursday, dt.date(2026, 11, 14), "day") == [
        dt.date(2026, 11, 12),
        dt.date(2026, 11, 13),
        dt.date(2026, 11, 14),
    ]
    # weeks are labelled by their Monday, the first one may start before the range
    assert e.bucket_starts(thursday, dt.date(2026, 11, 24), "week") == [
        dt.date(2026, 11, 9),
        dt.date(2026, 11, 16),
        dt.date(2026, 11, 23),
    ]
    assert e.bucket_starts(dt.date(2026, 11, 9), dt.date(2026, 11, 15), "week") == [
        dt.date(2026, 11, 9)
    ]


@given(
    start=st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 1, 1)),
    days=st.integers(min_value=1, max_value=371),
)
def test_bucket_starts_property(start: dt.date, days: int) -> None:
    end = start + dt.timedelta(days=days - 1)
    kind = e.bucket_kind(days)
    starts = e.bucket_starts(start, end, kind)
    assert starts == sorted(set(starts))
    assert e.bucket_start(start, kind) == starts[0]
    assert e.bucket_start(end, kind) == starts[-1]
    if kind == "week":
        assert all(s.weekday() == 0 for s in starts)
    else:
        assert len(starts) == days


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        ({"a": 5, "b": 0.5}, {"a": 3, "b": 0.75}, {"a": 2, "b": -0.25}),
        ({"a": None}, {"a": 3}, {"a": None}),
        ({"a": 3}, {"a": None}, {"a": None}),
        ({"a": 3}, {}, {"a": None}),
        ({"a": 0.3}, {"a": 0.1}, {"a": 0.2}),  # float noise is rounded away
        ({"a": 0}, {"a": 0}, {"a": 0}),
    ],
)
def test_period_deltas_table(
    current: dict[str, float | None],
    previous: dict[str, float | None],
    expected: dict[str, float | None],
) -> None:
    result = e.period_deltas(current, previous)
    assert result.values == expected
    assert result.reason


@given(
    st.dictionaries(st.sampled_from("abc"), st.one_of(st.none(), st.integers(-1000, 1000))),
    st.dictionaries(st.sampled_from("abc"), st.one_of(st.none(), st.integers(-1000, 1000))),
)
def test_period_deltas_property(
    current: dict[str, int | None], previous: dict[str, int | None]
) -> None:
    result = e.period_deltas(current, previous).values
    assert set(result) == set(current)
    for key, value in result.items():
        now, before = current[key], previous.get(key)
        assert value == (None if now is None or before is None else now - before)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], 0),
        (["rest", "rest"], 0),
        (["done", "done", "done"], 3),
        (["done", "rest", "done"], 2),  # a rest day does not break the run
        (["done", "missed", "done", "done"], 2),
        (["done", "done", "missed", "done"], 2),
        (["done", "rest", "rest", "missed", "done"], 1),
        (["done", "in_progress", "done"], 1),
        (["done", "done", "planned"], 2),
        (["missed", "missed"], 0),
    ],
)
def test_longest_streak_table(statuses: list[str], expected: int) -> None:
    days = [(D + dt.timedelta(days=n), s) for n, s in enumerate(statuses)]
    result = e.longest_streak(reversed(days))  # the order of the input does not matter
    assert result.days == expected
    assert result.reason


@given(st.lists(st.sampled_from(["done", "rest", "missed", "planned", "in_progress"]), max_size=60))
def test_longest_streak_property(statuses: list[str]) -> None:
    days = [(D + dt.timedelta(days=n), s) for n, s in enumerate(statuses)]
    streak = e.longest_streak(days).days
    assert 0 <= streak <= statuses.count("done")
    # dropping the rest days never changes the answer
    assert streak == e.longest_streak([d for d in days if d[1] != "rest"]).days
    if not {"missed", "planned", "in_progress"} & set(statuses):
        assert streak == statuses.count("done")


@pytest.mark.parametrize(
    ("change", "span", "expected"),
    [(None, 10, None), (1.0, 0, None), (-0.5, 7, -0.5), (1.0, 14, 0.5), (0.0, 29, 0.0)],
)
def test_weekly_rate_table(change: float | None, span: int, expected: float | None) -> None:
    assert e.weekly_rate(change, span) == expected
