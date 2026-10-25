"""F10.2 Session completion: Σ min(actual, target) ÷ Σ target over the planned working sets.

Reps are compared as reps (weight-agnostic); timed sets compare seconds. A planned set that was
skipped or never logged contributes an `actual` of 0. Extra sets and extra exercises are not
planned working sets and never enter the sums. Planned sets without a positive target (for
example an open-ended set) are left out, because they have nothing to complete.

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
    achieved: float
    target: float
    explanation: str


def _fmt(value: float) -> str:
    return f"{value:g}"


def completion(sets: Sequence[PlannedSetResult]) -> Completion:
    """Completion of the given planned sets, rounded to 4 decimals and capped at 1."""
    counted = [s for s in sets if s.target is not None and s.target > 0]
    for s in counted:
        if s.actual is not None and (math.isnan(s.actual) or s.actual < 0):
            raise ValueError("actual must be a non-negative number")
    target = math.fsum(s.target for s in counted if s.target is not None)
    achieved = math.fsum(min(s.actual or 0.0, s.target or 0.0) for s in counted)
    if not counted or target <= 0:
        return Completion(
            None, 0.0, 0.0, "No planned working set has a target, so completion is undefined."
        )
    ratio = min(1.0, round(achieved / target, COMPLETION_DECIMALS))
    return Completion(
        ratio,
        achieved,
        target,
        f"Completion = Σ min(actual, target) ÷ Σ target over {len(counted)} planned working "
        f"sets = {_fmt(achieved)} ÷ {_fmt(target)} = {ratio:.4f}",
    )
