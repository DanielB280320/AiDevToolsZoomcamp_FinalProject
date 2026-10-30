"""D74 meal portion rescale: new portion factors for one meal day so its kcal follow a new target.

Pure: takes the day's planned meals as plain numbers and returns the new factors with an
explanation. The caller decides which days to rescale (from today on) and stores the result.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.engines import constants as c


@dataclass(frozen=True, slots=True)
class RescaleResult:
    factors: tuple[float, ...]
    day_kcal: float  # estimated day total at the new factors
    clamped: bool  # at least one meal sits at a bound, so the day may miss the target
    explanation: str


def _clamp(value: float) -> float:
    bounded = min(c.RESCALE_PORTION_MAX, max(c.RESCALE_PORTION_MIN, value))
    return min(c.RESCALE_PORTION_MAX, max(c.RESCALE_PORTION_MIN, round(bounded, 2)))


def rescale_portions(
    factors: Sequence[float], kcal: Sequence[float], target_kcal: float
) -> RescaleResult:
    """Scale `factors` (current portion factor of each meal) so the day approaches `target_kcal`.

    `kcal[i]` is meal i's kcal at its current factor. All unclamped portions move together by the
    same ratio; a portion that hits a bound stays there and the rest take up the difference.
    Factors are always inside `RESCALE_PORTION_MIN..RESCALE_PORTION_MAX`.
    """
    if len(factors) != len(kcal):
        raise ValueError("factors and kcal must have the same length")
    if target_kcal <= 0 or not math.isfinite(target_kcal):
        raise ValueError("target_kcal must be a positive finite number")
    current = [float(f) for f in factors]
    per_factor = [k / f if f > 0 else 0.0 for k, f in zip(kcal, current, strict=True)]
    new = list(current)

    def total() -> float:
        return math.fsum(p * f for p, f in zip(per_factor, new, strict=True))

    start = total()
    if start <= 0:
        return RescaleResult(tuple(new), start, False, "No kcal in this day, portions unchanged.")
    for _ in range(c.RESCALE_PASSES):
        now = total()
        if abs(now - target_kcal) <= c.RESCALE_KCAL_TOLERANCE * target_kcal:
            break
        free = [
            i
            for i, f in enumerate(new)
            if per_factor[i] > 0
            and not (now < target_kcal and f >= c.RESCALE_PORTION_MAX)
            and not (now > target_kcal and f <= c.RESCALE_PORTION_MIN)
        ]
        free_kcal = math.fsum(per_factor[i] * new[i] for i in free)
        if free_kcal <= 0:
            break
        scale = max(0.0, (target_kcal - (now - free_kcal)) / free_kcal)
        updated = list(new)
        for i in free:
            updated[i] = _clamp(new[i] * scale)
        if updated == new:
            break
        new = updated
    end = total()
    clamped = (
        any(
            f in (c.RESCALE_PORTION_MIN, c.RESCALE_PORTION_MAX)
            for f, p in zip(new, per_factor, strict=True)
            if p > 0
        )
        and abs(end - target_kcal) > c.RESCALE_KCAL_TOLERANCE * target_kcal
    )
    text = (
        f"Day planned at {round(start)} kcal, new target {round(target_kcal)} kcal: "
        f"portions scaled to about {round(end)} kcal."
    )
    if clamped:
        text += (
            f" Portions are limited to {c.RESCALE_PORTION_MIN}-{c.RESCALE_PORTION_MAX}x, "
            "so the day stays off target."
        )
    return RescaleResult(tuple(new), end, clamped, text)
