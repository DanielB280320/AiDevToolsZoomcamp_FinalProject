"""F12.2 Nutrition completion: planned meals eaten (as planned or adjusted) / planned meals.

Skipped and unlogged planned meals do not count as eaten. Extra food is not a planned meal and
never enters the ratio. No planned meals means no ratio (`None`), so a day without a meal plan is
not shown as 0 %.

Pure (ADR 0004): plain inputs in, a ratio with an `explanation` out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

COUNTS_AS_EATEN = frozenset({"eaten", "adjusted"})
COMPLETION_DECIMALS = 4


@dataclass(frozen=True, slots=True)
class NutritionCompletion:
    ratio: float | None
    eaten: int
    planned: int
    explanation: str


def nutrition_completion(statuses: Sequence[str | None]) -> NutritionCompletion:
    """`statuses` has one entry per planned meal: its log status, or `None` when not logged."""
    planned = len(statuses)
    if planned == 0:
        return NutritionCompletion(None, 0, 0, "No meals are planned for this day.")
    eaten = sum(1 for status in statuses if status in COUNTS_AS_EATEN)
    ratio = round(eaten / planned, COMPLETION_DECIMALS)
    return NutritionCompletion(
        ratio,
        eaten,
        planned,
        f"{eaten} of {planned} planned meals eaten (skipped and unlogged meals do not count).",
    )
