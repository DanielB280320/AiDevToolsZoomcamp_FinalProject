"""F6.1 Meal macros and diet/allergen composition of a meal.

Macros of one item: `per-100 g value x grams / 100`, for kcal, protein, carbs and fat. A meal's
totals are the sum of the unrounded item values, rounded once at the end (kcal to a whole
`Kcal`, half up; grams to one decimal), so the totals do not drift with the number of items.
Item macros are rounded the same way for display.

A meal suits a diet when every food in it carries that diet's tag (`omnivore` suits everything);
its allergens are the union of the foods' allergens. An empty meal has zero macros and, vacuously,
every diet tag.

Pure (ADR 0004): plain inputs in, results with an `explanation` out.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

FORMULA = "per-100 g value x grams / 100, summed over the foods"
DIET_TAGS: tuple[str, ...] = ("vegetarian", "vegan", "pescatarian")


@dataclass(frozen=True, slots=True)
class Per100g:
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True, slots=True)
class Macros:
    kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True, slots=True)
class MealMacros:
    items: tuple[Macros, ...]
    totals: Macros
    explanation: str


def _check(value: float, what: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{what} must be a finite number >= 0")


def _round_kcal(value: float) -> int:
    return math.floor(value + 0.5)


def _round_grams(value: float) -> float:
    return math.floor(value * 10 + 0.5) / 10


def _scaled(food: Per100g, grams: float) -> tuple[float, float, float, float]:
    _check(grams, "grams")
    for what, value in (
        ("kcal", food.kcal),
        ("protein", food.protein_g),
        ("carbs", food.carbs_g),
        ("fat", food.fat_g),
    ):
        _check(value, what)
    factor = grams / 100
    return food.kcal * factor, food.protein_g * factor, food.carbs_g * factor, food.fat_g * factor


def _rounded(kcal: float, protein: float, carbs: float, fat: float) -> Macros:
    return Macros(_round_kcal(kcal), _round_grams(protein), _round_grams(carbs), _round_grams(fat))


def item_macros(food: Per100g, grams: float) -> Macros:
    """Macros of `grams` of a food."""
    return _rounded(*_scaled(food, grams))


def meal_macros(items: Sequence[tuple[Per100g, float]]) -> MealMacros:
    """Per-item macros and the meal totals for `(food per 100 g, grams)` pairs."""
    scaled = [_scaled(food, grams) for food, grams in items]
    sums = [math.fsum(column) for column in zip(*scaled, strict=True)] if scaled else [0.0] * 4
    totals = _rounded(*sums)
    explanation = (
        f"{len(scaled)} food(s): {FORMULA}; totals {totals.kcal} kcal, {totals.protein_g} g "
        f"protein, {totals.carbs_g} g carbs, {totals.fat_g} g fat."
    )
    return MealMacros(tuple(_rounded(*row) for row in scaled), totals, explanation)


def meal_diet_tags(foods_tags: Iterable[Iterable[str]]) -> tuple[str, ...]:
    """Diet tags every food carries (in `DIET_TAGS` order)."""
    tag_sets = [set(tags) for tags in foods_tags]
    return tuple(tag for tag in DIET_TAGS if all(tag in tags for tags in tag_sets))


def meal_allergens(foods_allergens: Iterable[Iterable[str]]) -> tuple[str, ...]:
    """Union of the foods' allergens, sorted."""
    return tuple(sorted({a for allergens in foods_allergens for a in allergens}))


def suits_diet(meal_tags: Iterable[str], diet: str) -> bool:
    """True when a meal with these derived tags suits `diet` (`omnivore` suits every meal)."""
    return diet == "omnivore" or diet in set(meal_tags)
