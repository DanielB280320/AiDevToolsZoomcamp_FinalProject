"""F7/F8 meal swap suggestions (D86): up to 3 alternatives with similar kcal to a planned meal.

Pure (ADR 0004): meals and the week's usage come in as plain data, the ranked alternatives and a
reason go out. No database, HTTP or clock access, and no randomness: the same input gives the same
list (closest kcal first, ties by meal id).

An alternative qualifies when
- it carries the planned meal's slot, suits the diet and has none of the excluded allergens (the
  F7 filters, reused from the generator),
- it is not already used `MEAL_MAX_USES_PER_WEEK` times in the week and is not already in that day
  (the meal being replaced counts as in the day, so it is never offered back), and
- at the portion factor that matches the planned kcal, clamped to 0.75-1.5 and rounded like the
  generator does, its kcal are within `SWAP_KCAL_BAND` of the planned kcal.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from app.engines.constants import (
    MEAL_MAX_USES_PER_WEEK,
    MEAL_PORTION_DECIMALS,
    MEAL_PORTION_MAX,
    MEAL_PORTION_MIN,
    SWAP_KCAL_BAND,
    SWAP_MAX_ALTERNATIVES,
)
from app.engines.meal_plan import MealCandidate, eligible_meals


@dataclass(frozen=True, slots=True)
class SwapRequest:
    slot: str
    planned_kcal: float  # the planned meal's kcal at its current portion
    diet: str
    allergies: Collection[str] = ()
    day_meal_ids: Collection[str] = ()  # every meal already in that day (incl. the one replaced)
    week_uses: Mapping[str, int] | None = None  # times each meal is planned in the week


@dataclass(frozen=True, slots=True)
class SwapAlternative:
    meal_id: str
    portion_factor: float
    kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True, slots=True)
class SwapResult:
    alternatives: tuple[SwapAlternative, ...]
    reason: str


def _factor(planned_kcal: float, meal_kcal: float) -> float:
    clamped = min(MEAL_PORTION_MAX, max(MEAL_PORTION_MIN, planned_kcal / meal_kcal))
    return min(MEAL_PORTION_MAX, max(MEAL_PORTION_MIN, round(clamped, MEAL_PORTION_DECIMALS)))


def suggest_swaps(request: SwapRequest, meals: Sequence[MealCandidate]) -> SwapResult:
    """Up to `SWAP_MAX_ALTERNATIVES` alternatives for a planned meal, closest kcal first."""
    planned = request.planned_kcal
    if not math.isfinite(planned) or planned <= 0:
        raise ValueError("planned_kcal must be a positive finite number")
    uses = request.week_uses or {}
    in_day = set(request.day_meal_ids)
    band = SWAP_KCAL_BAND * planned
    fitting: list[tuple[float, str, MealCandidate, float]] = []
    for meal in eligible_meals(meals, request.diet, request.allergies):
        if (
            request.slot not in meal.slots
            or meal.id in in_day
            or uses.get(meal.id, 0) >= MEAL_MAX_USES_PER_WEEK
            or meal.kcal <= 0
        ):
            continue
        factor = _factor(planned, meal.kcal)
        distance = abs(meal.kcal * factor - planned)
        if distance <= band:
            fitting.append((distance, meal.id, meal, factor))
    fitting.sort(key=lambda t: (t[0], t[1]))
    chosen = fitting[:SWAP_MAX_ALTERNATIVES]
    alternatives = tuple(
        SwapAlternative(
            meal_id=meal.id,
            portion_factor=factor,
            kcal=math.floor(meal.kcal * factor + 0.5),
            protein_g=round(meal.protein_g * factor, 1),
            carbs_g=round(meal.carbs_g * factor, 1),
            fat_g=round(meal.fat_g * factor, 1),
        )
        for _, _, meal, factor in chosen
    )
    reason = (
        f"{len(alternatives)} of {len(fitting)} matching {request.slot} meal(s) within "
        f"+-{round(SWAP_KCAL_BAND * 100)} % of {round(planned)} kcal at portions "
        f"{MEAL_PORTION_MIN}-{MEAL_PORTION_MAX}x, closest kcal first; meals already in the day or "
        f"used {MEAL_MAX_USES_PER_WEEK}x this week, other diets and allergens are left out."
        if alternatives
        else f"No other {request.slot} meal fits within +-{round(SWAP_KCAL_BAND * 100)} % of "
        f"{round(planned)} kcal with the diet, allergies and weekly limits."
    )
    return SwapResult(alternatives, reason)
