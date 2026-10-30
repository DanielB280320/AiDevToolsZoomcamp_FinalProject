"""F14 adaptive calories: compare the two last weekly weight trends with the goal's expected rate.

Pure (ADR 0004): plain numbers in, a result with a `reason` out. The service layer reads the
weigh-ins, the targets and the goal, and stores the suggestion.

A week's trend is the change of the 7-day average (F14.1) from the day the week starts (the
Monday) to its last day (the Sunday), as a percentage of the starting average. A week trends
"high" above `expected + tolerance` and "low" below `expected - tolerance`. Two consecutive weeks
on the same side give a suggestion: -150 kcal when high (losing too slowly, or gaining too fast),
+150 kcal when low (losing too fast, or gaining too slowly). A -150 kcal step that would go below
the calorie floor (F3.6) is not suggested (D78).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.engines import constants as c

Action = Literal["decrease", "increase", "none"]


@dataclass(frozen=True)
class WeekTrend:
    start_avg_kg: float | None
    """7-day average ending on the week's Monday, `None` without weigh-ins in that window."""
    end_avg_kg: float | None
    """7-day average ending on the week's Sunday."""
    weigh_ins: int
    """Weigh-ins dated Monday to Sunday of the week."""


@dataclass(frozen=True)
class AdaptiveInput:
    goal: str
    current_kcal: int
    floor_kcal: int
    weeks: tuple[WeekTrend, WeekTrend]
    """The two complete weeks, oldest first."""


@dataclass(frozen=True)
class AdaptiveResult:
    action: Action
    delta_kcal: int
    """-150, +150, or 0 when there is no suggestion."""
    proposed_kcal: int
    expected_weekly_change_pct: float
    tolerance_pct: float
    observed_weekly_change_pct: tuple[float | None, float | None]
    insufficient_weigh_ins: bool
    """True when a week has fewer than 4 weigh-ins (F14.2): the athlete gets a hint."""
    reason: str


def weekly_change_pct(week: WeekTrend) -> float | None:
    """Percent change of the 7-day average over the week, rounded to 0.01; None without data."""
    if week.start_avg_kg is None or week.end_avg_kg is None or week.start_avg_kg <= 0:
        return None
    return round((week.end_avg_kg - week.start_avg_kg) / week.start_avg_kg * 100, 2)


def _none(
    data: AdaptiveInput,
    expected: float,
    tolerance: float,
    observed: tuple[float | None, float | None],
    reason: str,
    insufficient: bool = False,
) -> AdaptiveResult:
    return AdaptiveResult(
        "none", 0, data.current_kcal, expected, tolerance, observed, insufficient, reason
    )


def _side(change: float, expected: float, tolerance: float) -> int:
    """+1 above the tolerance band, -1 below it, 0 inside (band edges are inside)."""
    # Rounded so that a value exactly on the edge is not pushed out by float noise.
    if round(change - (expected + tolerance), 6) > 0:
        return 1
    if round(change - (expected - tolerance), 6) < 0:
        return -1
    return 0


def suggest(data: AdaptiveInput) -> AdaptiveResult:
    if data.goal not in c.ADAPTIVE_EXPECTED_WEEKLY_PCT:
        raise ValueError(f"unknown goal: {data.goal}")
    expected = c.ADAPTIVE_EXPECTED_WEEKLY_PCT[data.goal]
    tolerance = c.ADAPTIVE_TOLERANCE_PCT[data.goal]
    observed = (weekly_change_pct(data.weeks[0]), weekly_change_pct(data.weeks[1]))
    need = c.ADAPTIVE_MIN_WEIGH_INS_PER_WEEK
    if any(w.weigh_ins < need for w in data.weeks):
        counts = " and ".join(str(w.weigh_ins) for w in data.weeks)
        return _none(
            data,
            expected,
            tolerance,
            observed,
            f"No calorie suggestion: at least {need} weigh-ins are needed in each of the last two "
            f"weeks, and there were {counts}. Weigh in more often.",
            insufficient=True,
        )
    if observed[0] is None or observed[1] is None:
        return _none(
            data,
            expected,
            tolerance,
            observed,
            "No calorie suggestion: there are not enough earlier weigh-ins to measure the "
            "weekly trend.",
        )
    sides = (_side(observed[0], expected, tolerance), _side(observed[1], expected, tolerance))
    band = f"{expected - tolerance:+g} % to {expected + tolerance:+g} %"
    trend = f"{observed[0]:+g} % and {observed[1]:+g} %"
    if sides[0] == 0 or sides[0] != sides[1]:
        return _none(
            data,
            expected,
            tolerance,
            observed,
            f"No calorie change: the weekly trends ({trend}) are not outside the expected band "
            f"({band}) in the same direction for two weeks in a row.",
        )
    if sides[0] > 0:
        delta, proposed = -c.ADAPTIVE_STEP_KCAL, data.current_kcal - c.ADAPTIVE_STEP_KCAL
        why = "above the expected band"
        verb = "Lower"
    else:
        delta, proposed = c.ADAPTIVE_STEP_KCAL, data.current_kcal + c.ADAPTIVE_STEP_KCAL
        why = "below the expected band"
        verb = "Raise"
    if proposed < data.floor_kcal:
        return _none(
            data,
            expected,
            tolerance,
            observed,
            f"No calorie suggestion: your weekly trends ({trend}) are {why} ({band}), but "
            f"lowering {data.current_kcal} kcal by {c.ADAPTIVE_STEP_KCAL} would go below the "
            f"calorie floor of {data.floor_kcal} kcal.",
        )
    return AdaptiveResult(
        "decrease" if delta < 0 else "increase",
        delta,
        proposed,
        expected,
        tolerance,
        observed,
        False,
        f"{verb} your target by {c.ADAPTIVE_STEP_KCAL} kcal to {proposed} kcal (estimated): your "
        f"weekly weight trends ({trend}) were {why} ({band}) two weeks in a row.",
    )
