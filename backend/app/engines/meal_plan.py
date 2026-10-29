"""F7 Meal plan generator: 7 meal days from the daily targets, slot split, diet and allergies.

Pure (ADR 0004): meals come in as plain data, the plan and its warnings go out. No database,
HTTP or clock access. Randomness is a small seeded generator of our own (SplitMix64) so the same
inputs and seed always give the same plan on every platform and Python version (F7.4).

How a plan is built (spec F7, D68):
- The daily kcal target is split over the slots by meals per day (`MEAL_SLOT_SPLIT`).
- Candidates for a slot must carry the slot, suit the diet and contain none of the allergens
  (F7.3, F6.5). A meal is used at most `MEAL_MAX_USES_PER_WEEK` times in the week (F7.2) and at
  most once a day.
- For each day several random combinations are tried. In each, a slot picks (at random) a meal
  whose portion factor for the slot's kcal falls inside 0.75-1.5; when none does, the meal
  closest to the range. The day's factors are then rescaled together towards the day target and
  clamped to 0.75-1.5, rounded to `MEAL_PORTION_DECIMALS`.
- The first combination within +-5 % kcal and with protein >= 90 % of the target is kept;
  otherwise the best attempt is returned and the day carries a warning (F7 "no feasible
  combination").
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from app.engines.constants import (
    MEAL_DAY_ATTEMPTS,
    MEAL_KCAL_TOLERANCE,
    MEAL_MAX_USES_PER_WEEK,
    MEAL_PORTION_DECIMALS,
    MEAL_PORTION_MAX,
    MEAL_PORTION_MIN,
    MEAL_PROTEIN_MIN_FRACTION,
    MEAL_SCALE_PASSES,
    MEAL_SLOT_SPLIT,
    MEAL_WARNING_KCAL,
    MEAL_WARNING_PROTEIN,
    MEAL_WARNING_SLOT,
)

WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_MASK = (1 << 64) - 1

# --- inputs ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MealCandidate:
    """A meal as plain data: its macros at portion factor 1 and the tags derived from its foods."""

    id: str
    slots: Sequence[str]
    diet_tags: Collection[str]  # diets the meal suits besides omnivore (F6)
    allergens: Collection[str]
    kcal: float
    protein_g: float


@dataclass(frozen=True, slots=True)
class MealPlanRequest:
    kcal: float  # daily target (F3)
    protein_g: float  # daily target (F3)
    meals_per_day: int  # 3 | 4 | 5
    diet: str  # omnivore | vegetarian | vegan | pescatarian
    allergies: Collection[str] = ()
    seed: int = 0


# --- outputs --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeneratedMeal:
    slot: str
    meal_id: str
    portion_factor: float
    kcal: int
    protein_g: float


@dataclass(frozen=True, slots=True)
class GeneratedMealDay:
    weekday: str
    meals: tuple[GeneratedMeal, ...]
    total_kcal: int
    total_protein_g: float
    warning: str | None


@dataclass(frozen=True, slots=True)
class GeneratedMealPlan:
    days: tuple[GeneratedMealDay, ...]
    warnings: tuple[str, ...]
    explanation: str


# --- seeded randomness ----------------------------------------------------------------------


def plan_seed(user_id_int: int, iso_year: int, iso_week: int) -> int:
    """Spec F7 `seed = user_id + ISO week`; the ISO year is folded in so weeks do not repeat."""
    return (user_id_int + iso_year * 100 + iso_week) & _MASK


class _Rng:
    """SplitMix64: a tiny deterministic generator, identical on every platform."""

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK

    def next_float(self) -> float:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        z ^= z >> 31
        return (z >> 11) / float(1 << 53)


# --- generator ------------------------------------------------------------------------------


def slot_targets(kcal: float, meals_per_day: int) -> tuple[tuple[str, float], ...]:
    """The slots of a day with their kcal share (spec F7 table)."""
    if meals_per_day not in MEAL_SLOT_SPLIT:
        raise ValueError("meals_per_day must be 3, 4 or 5")
    return tuple((slot, kcal * share) for slot, share in MEAL_SLOT_SPLIT[meals_per_day])


def eligible_meals(
    meals: Sequence[MealCandidate], diet: str, allergies: Collection[str]
) -> list[MealCandidate]:
    """Meals that suit the diet and contain no excluded allergen (F7.3), sorted by id."""
    excluded = set(allergies)
    return sorted(
        (
            m
            for m in meals
            if (diet == "omnivore" or diet in set(m.diet_tags)) and not excluded & set(m.allergens)
        ),
        key=lambda m: m.id,
    )


def _round_factor(value: float) -> float:
    clamped = min(MEAL_PORTION_MAX, max(MEAL_PORTION_MIN, value))
    factor = round(clamped, MEAL_PORTION_DECIMALS)
    return min(MEAL_PORTION_MAX, max(MEAL_PORTION_MIN, factor))


def _rescale(meals: list[MealCandidate], factors: list[float], target: float) -> list[float]:
    """Move the day total towards `target` by scaling all unclamped portions together."""
    for _ in range(MEAL_SCALE_PASSES):
        total = math.fsum(f * m.kcal for f, m in zip(factors, meals, strict=True))
        if total <= 0 or abs(total - target) <= 0.005 * target:
            break
        scale = target / total
        new = [_round_factor(f * scale) for f in factors]
        if new == factors:
            break
        factors = new
    return factors


@dataclass(frozen=True, slots=True)
class _Attempt:
    slots: tuple[str, ...]
    meals: tuple[MealCandidate, ...]
    factors: tuple[float, ...]
    missing_slot: str | None

    def kcal(self) -> float:
        return math.fsum(f * m.kcal for f, m in zip(self.factors, self.meals, strict=True))

    def protein(self) -> float:
        return math.fsum(f * m.protein_g for f, m in zip(self.factors, self.meals, strict=True))


def _pick(pool: list[MealCandidate], slot_kcal: float, rng: _Rng) -> MealCandidate:
    """A random meal whose factor for `slot_kcal` is in range, else the closest to the range."""
    fitting = [
        m for m in pool if m.kcal > 0 and MEAL_PORTION_MIN <= slot_kcal / m.kcal <= MEAL_PORTION_MAX
    ]
    if fitting:
        return fitting[min(int(rng.next_float() * len(fitting)), len(fitting) - 1)]

    def distance(m: MealCandidate) -> float:
        ratio = slot_kcal / m.kcal if m.kcal > 0 else math.inf
        return max(MEAL_PORTION_MIN - ratio, ratio - MEAL_PORTION_MAX, 0.0)

    return min(pool, key=lambda m: (distance(m), m.id))


def _attempt(
    pools: dict[str, list[MealCandidate]],
    uses: dict[str, int],
    slots: Sequence[tuple[str, float]],
    day_kcal: float,
    rng: _Rng,
) -> _Attempt:
    chosen: list[MealCandidate] = []
    chosen_slots: list[str] = []
    factors: list[float] = []
    missing: str | None = None
    used_today: set[str] = set()
    for slot, slot_kcal in slots:
        pool = [
            m
            for m in pools.get(slot, [])
            if m.id not in used_today and uses.get(m.id, 0) < MEAL_MAX_USES_PER_WEEK
        ]
        if not pool:
            missing = missing or slot
            continue
        meal = _pick(pool, slot_kcal, rng)
        used_today.add(meal.id)
        chosen.append(meal)
        chosen_slots.append(slot)
        factors.append(_round_factor(slot_kcal / meal.kcal if meal.kcal > 0 else 1.0))
    factors = _rescale(chosen, factors, day_kcal)
    return _Attempt(tuple(chosen_slots), tuple(chosen), tuple(factors), missing)


def _score(attempt: _Attempt, req: MealPlanRequest) -> tuple[bool, bool, float, float]:
    kcal_error = abs(attempt.kcal() - req.kcal) / req.kcal if req.kcal > 0 else 0.0
    protein_short = max(0.0, 1 - attempt.protein() / req.protein_g) if req.protein_g > 0 else 0.0
    return (
        kcal_error > MEAL_KCAL_TOLERANCE,
        protein_short > 1 - MEAL_PROTEIN_MIN_FRACTION,
        protein_short,
        kcal_error,
    )


def _rank(attempt: _Attempt, req: MealPlanRequest) -> tuple[bool, bool, float, float]:
    """Sort key of an attempt (smaller is better); a missing slot always counts as off target."""
    score = _score(attempt, req)
    return (True, *score[1:]) if attempt.missing_slot is not None else score


def _day_warning(
    total_kcal: float, total_protein: float, missing_slot: str | None, req: MealPlanRequest
) -> str | None:
    parts: list[str] = []
    if missing_slot is not None:
        parts.append(MEAL_WARNING_SLOT.format(slot=missing_slot))
    if abs(total_kcal - req.kcal) > MEAL_KCAL_TOLERANCE * req.kcal:
        parts.append(MEAL_WARNING_KCAL)
    if total_protein < MEAL_PROTEIN_MIN_FRACTION * req.protein_g:
        parts.append(MEAL_WARNING_PROTEIN)
    return "; ".join(parts) if parts else None


def generate_meal_plan(
    request: MealPlanRequest, meals: Sequence[MealCandidate]
) -> GeneratedMealPlan:
    """Seven meal days (Monday to Sunday) for `request`, from the library `meals`."""
    if not math.isfinite(request.kcal) or request.kcal <= 0:
        raise ValueError("kcal must be a positive finite number")
    if not math.isfinite(request.protein_g) or request.protein_g < 0:
        raise ValueError("protein_g must be a finite number >= 0")
    slots = slot_targets(request.kcal, request.meals_per_day)
    usable = eligible_meals(meals, request.diet, request.allergies)
    pools = {slot: [m for m in usable if slot in m.slots] for slot, _ in slots}
    rng = _Rng(request.seed)
    uses: dict[str, int] = {}
    days: list[GeneratedMealDay] = []
    for weekday in WEEKDAYS:
        best = _attempt(pools, uses, slots, request.kcal, rng)
        best_score = _rank(best, request)
        for _ in range(MEAL_DAY_ATTEMPTS - 1):
            if best_score[:2] == (False, False):
                break
            attempt = _attempt(pools, uses, slots, request.kcal, rng)
            score = _rank(attempt, request)
            if score < best_score:
                best, best_score = attempt, score
        for meal in best.meals:
            uses[meal.id] = uses.get(meal.id, 0) + 1
        planned = tuple(
            GeneratedMeal(
                slot=slot,
                meal_id=meal.id,
                portion_factor=factor,
                kcal=math.floor(meal.kcal * factor + 0.5),
                protein_g=round(meal.protein_g * factor, 1),
            )
            for slot, meal, factor in zip(best.slots, best.meals, best.factors, strict=True)
        )
        total_kcal = sum(p.kcal for p in planned)
        total_protein = round(math.fsum(p.protein_g for p in planned), 1)
        days.append(
            GeneratedMealDay(
                weekday=weekday,
                meals=planned,
                total_kcal=total_kcal,
                total_protein_g=total_protein,
                warning=_day_warning(total_kcal, total_protein, best.missing_slot, request),
            )
        )
    warnings = tuple(dict.fromkeys(d.warning for d in days if d.warning))
    explanation = (
        f"{request.meals_per_day} meals/day from {len(usable)} meal(s) matching the "
        f"{request.diet} diet and allergies; each day aims at {round(request.kcal)} kcal "
        f"(+-{round(MEAL_KCAL_TOLERANCE * 100)} %) and >= "
        f"{round(MEAL_PROTEIN_MIN_FRACTION * 100)} % of {round(request.protein_g)} g protein, "
        f"portions {MEAL_PORTION_MIN}-{MEAL_PORTION_MAX}x, each meal at most "
        f"{MEAL_MAX_USES_PER_WEEK}x a week."
    )
    return GeneratedMealPlan(tuple(days), warnings, explanation)
