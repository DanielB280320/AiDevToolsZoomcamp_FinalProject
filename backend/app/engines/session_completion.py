"""F10.2 Session completion: the average, over the planned working sets, of each set's
min(actual ÷ target, 1) (D110).

Every planned set weighs the same, so reps and seconds are never added together: a 600 s timed
set is one set, not 600 units next to 6-rep sets. Reps are compared as reps (weight-agnostic);
timed sets compare seconds. A planned set that was skipped or never logged scores 0. Extra sets
and extra exercises are not planned working sets and never enter the average. Planned sets
without a positive target (for example an open-ended set) are left out, because they have
nothing to complete.

Pure (ADR 0004): plain inputs in, a ratio with an `explanation` out.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

COMPLETION_DECIMALS = 4  # matches Numeric(5, 4) in the database


@dataclass(frozen=True, slots=True)
class PlannedSetResult:
    """One planned working set: its target (reps or seconds) and what was actually done."""

    target: float | None
    actual: float | None = None  # None / skipped / never logged count as 0


@dataclass(frozen=True, slots=True)
class Completion:
    ratio: float | None  # None when there is no positive target at all
    achieved: float  # sum of the per-set shares, each between 0 and 1
    target: float  # number of planned working sets that have a positive target
    explanation: str


def _fmt(value: float) -> str:
    return f"{value:g}"


def completion(sets: Sequence[PlannedSetResult]) -> Completion:
    """Completion of the given planned sets, rounded to 4 decimals and capped at 1."""
    counted = [s for s in sets if s.target is not None and s.target > 0]
    for s in counted:
        if s.actual is not None and (math.isnan(s.actual) or s.actual < 0):
            raise ValueError("actual must be a non-negative number")
    if not counted:
        return Completion(
            None, 0.0, 0.0, "No planned working set has a target, so completion is undefined."
        )
    # Per-set share of its own target, capped at 1: extra reps never make up for another set.
    achieved = math.fsum(min((s.actual or 0.0) / (s.target or 1.0), 1.0) for s in counted)
    target = float(len(counted))
    ratio = min(1.0, round(achieved / target, COMPLETION_DECIMALS))
    return Completion(
        ratio,
        achieved,
        target,
        f"Completion = Σ min(actual ÷ target, 1) ÷ {len(counted)} planned working sets "
        f"= {_fmt(round(achieved, COMPLETION_DECIMALS))} ÷ {_fmt(target)} = {ratio:.4f}",
    )
