"""F6 seed data checks that need no database: shape, tags, allergens and the coverage matrix."""

import pytest

from app.engines.meal_macros import meal_diet_tags, suits_diet
from app.models.food import ALLERGENS, DIET_TAGS, MEAL_SLOTS
from app.seed_foods import SEED_FOODS, SEED_MEALS, food_id, meal_id

FOODS = {f.name: f for f in SEED_FOODS}
DIETS = ("omnivore", "vegetarian", "vegan", "pescatarian")

# Foods that must carry an allergen tag (F6.5), by name fragment.
KNOWN_ALLERGEN_FOODS = {
    "Rolled oats": "gluten",
    "Whole wheat bread": "gluten",
    "Whole wheat pasta, cooked": "gluten",
    "Whole wheat tortilla": "gluten",
    "Milk, semi-skimmed": "lactose",
    "Greek yogurt, nonfat": "lactose",
    "Cheddar cheese": "lactose",
    "Feta cheese": "lactose",
    "Mozzarella": "lactose",
    "Cottage cheese": "lactose",
    "Whey protein powder": "lactose",
    "Peanut butter": "nuts",
    "Almonds": "nuts",
    "Walnuts": "nuts",
    "Egg, whole": "eggs",
    "Tofu, firm": "soy",
    "Tempeh": "soy",
    "Soy milk, unsweetened": "soy",
    "Shrimp, cooked": "shellfish",
    "Salmon, cooked": "fish",
    "Tuna, canned in water": "fish",
    "Cod, cooked": "fish",
}


def _meal_tags(name: str) -> tuple[str, ...]:
    meal = next(m for m in SEED_MEALS if m.name == name)
    return meal_diet_tags(FOODS[food].diet_tags for food, _ in meal.items)


def test_there_are_at_least_50_meals_and_unique_names_and_ids() -> None:
    assert len(SEED_MEALS) >= 50
    assert len({m.name.lower() for m in SEED_MEALS}) == len(SEED_MEALS)
    assert len({meal_id(m.name) for m in SEED_MEALS}) == len(SEED_MEALS)
    assert len({f.name.lower() for f in SEED_FOODS}) == len(SEED_FOODS)
    assert len({food_id(f.name) for f in SEED_FOODS}) == len(SEED_FOODS)


def test_every_meal_item_references_a_seed_food_with_positive_grams() -> None:
    for meal in SEED_MEALS:
        assert meal.items, meal.name
        assert set(meal.slots) <= set(MEAL_SLOTS)
        for food, grams in meal.items:
            assert food in FOODS, (meal.name, food)
            assert 0 < grams <= 2000


def test_every_food_has_valid_tags_and_values() -> None:
    for food in SEED_FOODS:
        assert set(food.diet_tags) <= set(DIET_TAGS)
        assert set(food.allergen_tags) <= set(ALLERGENS)
        assert 0 <= food.kcal <= 900
        assert all(0 <= v <= 100 for v in (food.protein_g, food.carbs_g, food.fat_g))
        # Atwater sanity: stated kcal within 25 % (or 25 kcal) of 4/4/9 from the macros.
        estimate = 4 * food.protein_g + 4 * food.carbs_g + 9 * food.fat_g
        assert abs(estimate - food.kcal) <= max(25, 0.25 * food.kcal), food.name


def test_diet_tags_are_non_empty_unless_the_food_is_meat_or_poultry() -> None:
    """F6.5: a food with no diet tag suits omnivores only; that is an explicit choice, so it is
    limited to the listed meat/poultry foods."""
    meat = {f.name for f in SEED_FOODS if not f.diet_tags}
    assert meat == {
        "Chicken breast, cooked",
        "Turkey breast, cooked",
        "Beef mince 10% fat, cooked",
        "Beef sirloin steak, cooked",
        "Lean ham",
    }
    for food in SEED_FOODS:
        if "vegan" in food.diet_tags:
            assert {"vegetarian", "pescatarian"} <= set(food.diet_tags)
        if "vegetarian" in food.diet_tags:
            assert "pescatarian" in food.diet_tags


@pytest.mark.parametrize(("name", "allergen"), sorted(KNOWN_ALLERGEN_FOODS.items()))
def test_known_allergen_foods_carry_their_tag(name: str, allergen: str) -> None:
    assert allergen in FOODS[name].allergen_tags


def test_empty_allergen_list_only_for_foods_without_a_known_allergen() -> None:
    for food in SEED_FOODS:
        if not food.allergen_tags:
            assert food.name not in KNOWN_ALLERGEN_FOODS


def test_coverage_matrix_every_slot_has_a_meal_for_every_diet() -> None:
    matrix = {
        (slot, diet): [
            m.name for m in SEED_MEALS if slot in m.slots and suits_diet(_meal_tags(m.name), diet)
        ]
        for slot in MEAL_SLOTS
        for diet in DIETS
    }
    missing = [key for key, names in matrix.items() if not names]
    assert not missing, missing
    # Print the matrix (visible with `pytest -s`) so the coverage is easy to review.
    for slot in MEAL_SLOTS:
        print(slot, {diet: len(matrix[slot, diet]) for diet in DIETS})  # noqa: T201
