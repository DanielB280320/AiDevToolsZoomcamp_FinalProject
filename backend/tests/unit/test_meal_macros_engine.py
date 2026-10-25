"""F6.1 meal macros engine: table-driven and property tests."""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.meal_macros import (
    Macros,
    Per100g,
    item_macros,
    meal_allergens,
    meal_diet_tags,
    meal_macros,
    suits_diet,
)

OATS = Per100g(kcal=379, protein_g=13.2, carbs_g=67.7, fat_g=6.5)
GRAM = st.floats(min_value=0, max_value=2000, allow_nan=False)
FOOD = st.builds(
    Per100g,
    st.floats(0, 900, allow_nan=False),
    st.floats(0, 100, allow_nan=False),
    st.floats(0, 100, allow_nan=False),
    st.floats(0, 100, allow_nan=False),
)


@pytest.mark.parametrize(
    ("food", "grams", "expected"),
    [
        (Per100g(200, 10, 20, 5), 150, Macros(300, 15.0, 30.0, 7.5)),
        (Per100g(200, 10, 20, 5), 100, Macros(200, 10.0, 20.0, 5.0)),
        (Per100g(200, 10, 20, 5), 0, Macros(0, 0.0, 0.0, 0.0)),
        (OATS, 60, Macros(227, 7.9, 40.6, 3.9)),
        (Per100g(0, 0, 0, 0), 500, Macros(0, 0.0, 0.0, 0.0)),
        (Per100g(884, 0, 0, 100), 5, Macros(44, 0.0, 0.0, 5.0)),
    ],
)
def test_item_macros_table(food: Per100g, grams: float, expected: Macros) -> None:
    assert item_macros(food, grams) == expected


def test_150_g_of_a_200_kcal_food_is_300_kcal() -> None:
    result = meal_macros([(Per100g(200, 0, 0, 0), 150)])
    assert result.totals.kcal == 300
    assert "per-100 g" in result.explanation


def test_empty_meal_is_zeros() -> None:
    result = meal_macros([])
    assert result.totals == Macros(0, 0.0, 0.0, 0.0)
    assert result.items == ()
    assert result.explanation


def test_totals_sum_unrounded_items() -> None:
    # Three items of 0.5 kcal each: rounding per item would give 3, the sum gives 2 (1.5 -> 2).
    food = Per100g(0.5, 0, 0, 0)
    result = meal_macros([(food, 100)] * 3)
    assert [i.kcal for i in result.items] == [1, 1, 1]
    assert result.totals.kcal == 2


@pytest.mark.parametrize(
    "bad",
    [-1.0, math.nan, math.inf],
)
def test_negative_or_non_finite_inputs_are_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="grams"):
        item_macros(OATS, bad)
    with pytest.raises(ValueError, match="kcal"):
        item_macros(Per100g(bad, 0, 0, 0), 10)


@given(st.lists(st.tuples(FOOD, GRAM), max_size=8))
def test_totals_are_the_sum_of_items_within_rounding(items: list[tuple[Per100g, float]]) -> None:
    result = meal_macros(items)
    n = len(items)
    assert abs(result.totals.kcal - sum(i.kcal for i in result.items)) <= n / 2 + 1
    assert abs(result.totals.protein_g - sum(i.protein_g for i in result.items)) <= n * 0.05 + 0.1
    assert result.totals.kcal >= 0 and result.totals.fat_g >= 0


@given(FOOD, GRAM)
def test_macros_scale_linearly_with_grams(food: Per100g, grams: float) -> None:
    single = item_macros(food, grams)
    assert abs(single.kcal - food.kcal * grams / 100) <= 0.5 + 1e-9
    assert abs(single.carbs_g - food.carbs_g * grams / 100) <= 0.05 + 1e-9


@given(st.lists(st.tuples(FOOD, GRAM), max_size=6))
def test_item_order_does_not_change_the_totals(items: list[tuple[Per100g, float]]) -> None:
    assert meal_macros(items).totals == meal_macros(list(reversed(items))).totals


def test_diet_tags_are_the_intersection_of_the_foods() -> None:
    vegan = ("vegan", "vegetarian", "pescatarian")
    veg = ("vegetarian", "pescatarian")
    assert meal_diet_tags([vegan, vegan]) == ("vegetarian", "vegan", "pescatarian")
    assert meal_diet_tags([vegan, veg]) == ("vegetarian", "pescatarian")
    assert meal_diet_tags([veg, ("pescatarian",)]) == ("pescatarian",)
    assert meal_diet_tags([vegan, ()]) == ()


def test_allergens_are_the_union_and_omnivore_suits_everything() -> None:
    assert meal_allergens([("nuts",), ("gluten", "nuts"), ()]) == ("gluten", "nuts")
    assert suits_diet((), "omnivore")
    assert not suits_diet(("vegetarian",), "vegan")
    assert suits_diet(("vegan",), "vegan")
