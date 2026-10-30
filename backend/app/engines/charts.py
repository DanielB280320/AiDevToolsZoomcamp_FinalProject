"""F15 Chart series: set status, exercise history with personal records, rolling weight average.

Pure (ADR 0004): plain values in, results with a `reason` out. The service layer reads the rows
(set logs carry their target snapshots, F15.2) and shapes the response.
"""

from __future__ import annotations

import bisect
import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.engines import constants as c

SetStatus = Literal["met", "partial", "missed", "skipped", "extra"]
RATIO_DECIMALS = 4


@dataclass(frozen=True, slots=True)
class SetValues:
    """One set: the target it was planned or performed against and what was done."""

    target_reps: int | None = None
    target_weight_kg: float | None = None
    target_seconds: int | None = None
    reps: int | None = None
    weight_kg: float | None = None
    seconds: int | None = None


@dataclass(frozen=True, slots=True)
class SetOutcome:
    status: SetStatus
    completion: float | None
    reason: str


def set_outcome(
    values: SetValues, *, logged: bool, skipped: bool, extra: bool, timed: bool
) -> SetOutcome:
    """Status of one set (F15 session detail).

    `extra` sets were not planned; a planned set that was never logged is `missed`; one that was
    skipped is `skipped`. Otherwise `met` when the actual reaches the target (reps, or seconds for
    timed exercises, and the weight when the target has one), else `partial`. Completion is
    min(actual, target) / target of reps (seconds when timed), `None` without a positive target.
    """
    if extra:
        return SetOutcome("extra", None, "Not part of the plan.")
    if not logged:
        return SetOutcome("missed", 0.0, "The set was not logged.")
    if skipped:
        return SetOutcome("skipped", 0.0, "The set was skipped.")
    target = values.target_seconds if timed else values.target_reps
    actual = values.seconds if timed else values.reps
    completion: float | None = None
    if target is not None and target > 0:
        completion = round(min(actual or 0, target) / target, RATIO_DECIMALS)
    reached = target is None or (actual or 0) >= target
    if not timed and values.target_weight_kg is not None:
        reached = reached and (values.weight_kg or 0.0) >= values.target_weight_kg
    if reached:
        return SetOutcome("met", completion, "Actual reached the target.")
    return SetOutcome("partial", completion, "Actual is below the target.")


@dataclass(frozen=True, slots=True)
class LoggedSet:
    """A performed (not skipped) set of one exercise in one session, with its target snapshot."""

    set_no: int
    values: SetValues


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    session_id: str
    date: dt.date
    target_weight_kg: float | None
    target_reps: int | None
    target_seconds: int | None
    top_set_weight_kg: float | None
    top_set_reps: int | None
    top_set_seconds: int | None
    volume_kg: float
    is_pr: bool
    reason: str


def _rank(values: SetValues, timed: bool) -> tuple[float, float]:
    """Order of sets within an exercise: heavier, then more reps; longer for timed."""
    if timed:
        return (float(values.seconds or 0), 0.0)
    return (values.weight_kg or 0.0, float(values.reps or 0))


def exercise_history(
    sessions: Iterable[tuple[str, dt.date, Sequence[LoggedSet]]], *, timed: bool
) -> list[HistoryPoint]:
    """One point per session (oldest first) with the top set, volume and personal-record flag.

    The top set is the heaviest performed set (most reps on a tie; longest when timed), so a
    bodyweight exercise ranks by reps. A point is a personal record when its top set beats every
    earlier session's and is above zero. The target is the snapshot of the first set that has
    one, i.e. the target at the time of the session, never the current plan (F15.2).
    """
    points: list[HistoryPoint] = []
    best = (0.0, 0.0)
    for session_id, day, sets in sorted(sessions, key=lambda s: s[1]):
        ordered = sorted(sets, key=lambda s: s.set_no)
        if not ordered:
            continue
        top = max((s.values for s in ordered), key=lambda v: _rank(v, timed))
        rank = _rank(top, timed)
        is_pr = rank > best and rank > (0.0, 0.0)
        if is_pr:
            best = rank
        snapshot = next(
            (
                s.values
                for s in ordered
                if s.values.target_weight_kg is not None
                or s.values.target_reps is not None
                or s.values.target_seconds is not None
            ),
            SetValues(),
        )
        volume = sum((s.values.reps or 0) * (s.values.weight_kg or 0.0) for s in ordered)
        points.append(
            HistoryPoint(
                session_id,
                day,
                snapshot.target_weight_kg,
                snapshot.target_reps,
                snapshot.target_seconds,
                top.weight_kg,
                top.reps,
                top.seconds,
                round(volume, 2),
                is_pr,
                (
                    f"Volume = sum of reps x weight over {len(ordered)} performed sets = "
                    f"{volume:g} kg. "
                    + ("New personal record." if is_pr else "Not a personal record.")
                ),
            )
        )
    return points


def rolling_weight_average(
    weights: Iterable[tuple[dt.date, float]], days: Sequence[dt.date]
) -> list[float | None]:
    """F14.1 average of the weigh-ins dated `d - 6 .. d` for each `d` in `days`.

    Same rule as `body_tracking.seven_day_average` but one sort and a binary search per day, so
    a year of data stays cheap. Missing days are not counted; no weigh-in gives `None`.
    """
    ordered = sorted(dict(weights).items())
    dates = [d for d, _ in ordered]
    prefix = [0.0]
    for _, kg in ordered:
        prefix.append(prefix[-1] + kg)
    window = dt.timedelta(days=c.WEIGHT_AVERAGE_WINDOW_DAYS - 1)
    result: list[float | None] = []
    for day in days:
        lo = bisect.bisect_left(dates, day - window)
        hi = bisect.bisect_right(dates, day)
        result.append(None if hi == lo else (prefix[hi] - prefix[lo]) / (hi - lo))
    return result


def mean_ratio(values: Iterable[float | None]) -> float | None:
    """Mean of the values that exist (4 decimals); `None` when there are none."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present), RATIO_DECIMALS)


def week_start(day: dt.date) -> dt.date:
    """Monday of the ISO week of `day`."""
    return day - dt.timedelta(days=day.weekday())
