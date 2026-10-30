"""F14 Body tracking: 7-day weight average and the 2 % recalculation check.

Pure (ADR 0004): plain dates and numbers in, a result with an `explanation`/`reason` out. The
service layer reads the weigh-ins and decides what to store.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.engines import constants as c


@dataclass(frozen=True)
class WeightAverage:
    average_kg: float | None
    """Mean of the weigh-ins in the window, `None` when there are none."""
    count: int
    """Number of days in the window that have a weigh-in."""
    window_start: dt.date
    window_end: dt.date
    explanation: str


@dataclass(frozen=True)
class RecalcCheck:
    needed: bool
    change_pct: float
    """Signed change from the weight used for the targets, percent, rounded to 0.01."""
    reason: str


def seven_day_average(weights: Iterable[tuple[dt.date, float]], on: dt.date) -> WeightAverage:
    """F14.1: average of the weigh-ins dated `on - 6 .. on`; missing days are not counted.

    3 weigh-ins in the 7-day window average those 3. A date given twice keeps its last value.
    """
    start = on - dt.timedelta(days=c.WEIGHT_AVERAGE_WINDOW_DAYS - 1)
    in_window = {day: kg for day, kg in weights if start <= day <= on}
    if not in_window:
        return WeightAverage(
            None, 0, start, on, f"No weigh-ins between {start} and {on}, so there is no average."
        )
    average = sum(in_window.values()) / len(in_window)
    return WeightAverage(
        average,
        len(in_window),
        start,
        on,
        f"Average of {len(in_window)} weigh-in(s) between {start} and {on}; "
        "days without a weigh-in are not counted.",
    )


def check_recalculation(weight_used_kg: float, new_weight_kg: float) -> RecalcCheck:
    """F14: recalculation is needed when the weight moved at least 2 % from `weight_used_kg`.

    Compared with exact decimal arithmetic so that exactly 2.00 % counts and 1.9 % does not.
    """
    if weight_used_kg <= 0 or new_weight_kg <= 0:
        raise ValueError("weights must be positive")
    used, new = Decimal(repr(weight_used_kg)), Decimal(repr(new_weight_kg))
    change = (new - used) / used * 100
    threshold = Decimal(repr(c.RECALC_THRESHOLD_PCT))
    needed = abs(change) >= threshold
    pct = float(round(change, 2))
    direction = "up" if change > 0 else "down"
    if needed:
        reason = (
            f"Your weight is {direction} {abs(pct):g} % from the {weight_used_kg:g} kg your "
            f"targets use ({new_weight_kg:g} kg now), at least {c.RECALC_THRESHOLD_PCT:g} %, so "
            "recalculating your targets is suggested."
        )
    else:
        reason = (
            f"Your weight changed {abs(pct):g} % from the {weight_used_kg:g} kg your targets "
            f"use, below {c.RECALC_THRESHOLD_PCT:g} %, so no recalculation is suggested."
        )
    return RecalcCheck(needed, pct, reason)
