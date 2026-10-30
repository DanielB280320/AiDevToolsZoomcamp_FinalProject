"""F14.2 / F14.3 / F3.6: the adaptive calorie engine, table-driven plus properties."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines import adaptive_calories as ac
from app.engines import constants as c

START = 80.0


def week(change_pct: float | None, n: int = 5) -> ac.WeekTrend:
    if change_pct is None:
        return ac.WeekTrend(None, None, n)
    return ac.WeekTrend(START, START * (1 + change_pct / 100), n)


def run(
    goal: str,
    a: float | None,
    b: float | None,
    kcal: int = 2400,
    floor: int = 1500,
    n: tuple[int, int] = (5, 5),
) -> ac.AdaptiveResult:
    return ac.suggest(ac.AdaptiveInput(goal, kcal, floor, (week(a, n[0]), week(b, n[1]))))


@pytest.mark.parametrize(
    ("goal", "change", "action", "delta"),
    [
        # cutting: expected -0.75 +- 0.25 -> band -1.0 .. -0.5
        ("cutting", -0.2, "decrease", -150),  # losing too slowly
        ("cutting", 0.3, "decrease", -150),  # gaining
        ("cutting", -1.5, "increase", 150),  # losing too fast
        ("cutting", -0.75, "none", 0),
        ("cutting", -0.5, "none", 0),  # edge is inside
        ("cutting", -1.0, "none", 0),
        ("maintenance", 0.6, "decrease", -150),  # gaining
        ("maintenance", -0.6, "increase", 150),  # losing
        ("maintenance", 0.25, "none", 0),
        ("wellness", 0.6, "decrease", -150),
        ("wellness", -0.6, "increase", 150),
        ("recomposition", 0.6, "decrease", -150),
        ("recomposition", -0.6, "increase", 150),
        ("recomposition", -0.25, "none", 0),
        # muscle gain: expected +0.25 +- 0.15 -> band 0.10 .. 0.40
        ("muscle_gain", 0.8, "decrease", -150),  # gaining too fast
        ("muscle_gain", 0.0, "increase", 150),  # gaining too slowly
        ("muscle_gain", -0.5, "increase", 150),
        ("muscle_gain", 0.4, "none", 0),
        ("muscle_gain", 0.1, "none", 0),
    ],
)
def test_direction_and_amount_per_goal(goal, change, action, delta):
    r = run(goal, change, change)
    assert (r.action, r.delta_kcal) == (action, delta)
    assert r.proposed_kcal == 2400 + delta
    assert r.reason


def test_expected_rate_and_tolerance_are_reported():
    r = run("muscle_gain", 0.8, 0.9)
    assert (r.expected_weekly_change_pct, r.tolerance_pct) == (0.25, 0.15)
    assert r.observed_weekly_change_pct == (0.8, 0.9)


@pytest.mark.parametrize(
    ("a", "b"),
    [(-0.2, -1.5), (-1.5, -0.2), (-0.2, -0.75), (-0.75, -1.5)],
)
def test_needs_the_same_direction_in_both_weeks(a, b):
    r = run("cutting", a, b)
    assert r.action == "none"
    assert not r.insufficient_weigh_ins


@pytest.mark.parametrize("n", [(3, 5), (5, 3), (0, 0), (3, 3)])
def test_fewer_than_four_weigh_ins_in_either_week_gives_no_suggestion(n):
    r = run("cutting", -0.2, -0.2, n=n)  # would otherwise be a -150 suggestion
    assert r.action == "none" and r.delta_kcal == 0
    assert r.insufficient_weigh_ins
    assert "weigh" in r.reason


def test_exactly_four_weigh_ins_are_enough():
    assert run("cutting", -0.2, -0.2, n=(4, 4)).action == "decrease"


def test_missing_averages_give_no_suggestion_and_no_hint():
    r = run("cutting", None, -0.2)
    assert r.action == "none" and not r.insufficient_weigh_ins


@pytest.mark.parametrize(
    ("kcal", "floor", "action", "proposed"),
    [
        (1650, 1500, "decrease", 1500),  # lands exactly on the floor
        (1649, 1500, "none", 1649),  # would go below: not suggested
        (1500, 1500, "none", 1500),
        (1300, 1500, "none", 1300),  # already under (older targets)
        (1350, 1200, "decrease", 1200),
    ],
)
def test_never_below_the_calorie_floor(kcal, floor, action, proposed):
    r = run("cutting", -0.2, -0.2, kcal=kcal, floor=floor)
    assert r.action == action
    assert r.proposed_kcal == proposed
    if action == "none":
        assert "floor" in r.reason


def test_raising_is_allowed_below_the_floor():
    r = run("cutting", -1.5, -1.5, kcal=1400, floor=1500)
    assert (r.action, r.proposed_kcal) == ("increase", 1550)


def test_unknown_goal_is_rejected():
    with pytest.raises(ValueError):
        run("bulk", 0.0, 0.0)


@given(
    goal=st.sampled_from(sorted(c.ADAPTIVE_EXPECTED_WEEKLY_PCT)),
    a=st.floats(-5, 5),
    b=st.floats(-5, 5),
    kcal=st.integers(1000, 6000),
    floor=st.sampled_from([1200, 1350, 1500]),
    n=st.tuples(st.integers(0, 8), st.integers(0, 8)),
)
def test_properties(goal, a, b, kcal, floor, n):
    r = run(goal, a, b, kcal=kcal, floor=floor, n=n)
    assert r.delta_kcal in (-150, 0, 150)
    assert r.proposed_kcal == kcal + r.delta_kcal
    assert r.reason
    if r.action == "decrease":
        assert r.proposed_kcal >= floor
    if min(n) < 4:
        assert r.action == "none"
    # opposite sides never produce a change
    if (a - c.ADAPTIVE_EXPECTED_WEEKLY_PCT[goal]) * (b - c.ADAPTIVE_EXPECTED_WEEKLY_PCT[goal]) < 0:
        assert r.action == "none"
