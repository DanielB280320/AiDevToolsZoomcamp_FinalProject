"""F7 meal plan generator: table-driven rules plus property tests (F7.1-F7.4).

The realistic library is the real seed (`SEED_MEALS`, macros from the F6.1 engine); property
tests also run on random synthetic libraries so the guarantees hold for any input.
"""

from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.constants import (
    MEAL_MAX_USES_PER_WEEK,
    MEAL_PORTION_MAX,
    MEAL_PORTION_MIN,
    MEAL_SLOT_SPLIT,
    MEAL_WARNING_PROTEIN,
)
from app.engines.meal_macros import Per100g, meal_allergens, meal_diet_tags, meal_macros
from app.engines.meal_plan import (
    WEEKDAYS,
    GeneratedMealPlan,
    MealCandidate,
    MealPlanRequest,
    eligible_meals,
    generate_meal_plan,
    plan_seed,
    slot_targets,
)
from app.seed_foods import SEED_FOODS, SEED_MEALS

_FOODS = {f.name: f for f in SEED_FOODS}


def _seed_candidates() -> list[MealCandidate]:
    result = []
    for i, meal in enumerate(SEED_MEALS):
        foods = [(_FOODS[name], grams) for name, grams in meal.items]
        totals = meal_macros(
            [(Per100g(f.kcal, f.protein_g, f.carbs_g, f.fat_g), g) for f, g in foods]
        ).totals
        result.append(
            MealCandidate(
                id=f"m{i:03d}",
                slots=meal.slots,
                diet_tags=meal_diet_tags(f.diet_tags for f, _ in foods),
                allergens=meal_allergens(f.allergen_tags for f, _ in foods),
                kcal=totals.kcal,
                protein_g=totals.protein_g,
            )
        )
    return result


LIBRARY = _seed_candidates()
BY_ID = {m.id: m for m in LIBRARY}
DIETS = ("omnivore", "vegetarian", "vegan", "pescatarian")
ALLERGENS = ("gluten", "lactose", "nuts", "eggs", "soy", "shellfish", "fish")


def _request(**overrides: object) -> MealPlanRequest:
    values: dict[str, object] = {
        "kcal": 2200,
        "protein_g": 150,
        "meals_per_day": 4,
        "diet": "omnivore",
        "allergies": (),
        "seed": 7,
    }
    values.update(overrides)
    return MealPlanRequest(**values)  # type: ignore[arg-type]


def _check_invariants(
    plan: GeneratedMealPlan,
    req: MealPlanRequest,
    library: dict[str, MealCandidate],
) -> None:
    assert [d.weekday for d in plan.days] == list(WEEKDAYS)
    uses: Counter[str] = Counter()
    for day in plan.days:
        # F7.1: within +-5 % kcal and protein >= 90 %, or the day carries a warning.
        within = abs(day.total_kcal - req.kcal) <= 0.05 * req.kcal
        protein_ok = day.total_protein_g >= 0.9 * req.protein_g
        assert (within and protein_ok) or day.warning, (day.total_kcal, day.total_protein_g)
        ids = [m.meal_id for m in day.meals]
        assert len(ids) == len(set(ids))
        for planned in day.meals:
            uses[planned.meal_id] += 1
            meal = library[planned.meal_id]
            assert planned.slot in meal.slots
            assert MEAL_PORTION_MIN <= planned.portion_factor <= MEAL_PORTION_MAX
            # F7.3: diet and allergy filters are never violated.
            assert req.diet == "omnivore" or req.diet in meal.diet_tags
            assert not set(req.allergies) & set(meal.allergens)
        slots = [m.slot for m in day.meals]
        expected = [s for s, _ in MEAL_SLOT_SPLIT[req.meals_per_day]]
        remaining = iter(expected)  # the day's slots are a subsequence of the split order
        assert all(slot in remaining for slot in slots)
    # F7.2: no meal more than twice a week.
    assert all(count <= MEAL_MAX_USES_PER_WEEK for count in uses.values())
    assert plan.warnings == tuple(dict.fromkeys(d.warning for d in plan.days if d.warning))


# ───────────── table-driven ─────────────


@pytest.mark.parametrize(
    ("meals_per_day", "expected"),
    [
        (3, [("breakfast", 0.25), ("lunch", 0.35), ("dinner", 0.40)]),
        (4, [("breakfast", 0.25), ("lunch", 0.30), ("snack", 0.15), ("dinner", 0.30)]),
        (
            5,
            [
                ("breakfast", 0.20),
                ("snack", 0.10),
                ("lunch", 0.30),
                ("snack", 0.10),
                ("dinner", 0.30),
            ],
        ),
    ],
)
def test_slot_split_follows_the_spec_table(
    meals_per_day: int, expected: list[tuple[str, float]]
) -> None:
    targets = slot_targets(1000, meals_per_day)
    assert [(s, round(k / 1000, 2)) for s, k in targets] == expected
    assert sum(k for _, k in targets) == pytest.approx(1000)


def test_invalid_meals_per_day_is_rejected() -> None:
    with pytest.raises(ValueError, match="meals_per_day"):
        slot_targets(2000, 2)


@pytest.mark.parametrize("kcal", [0, -5, float("nan"), float("inf")])
def test_invalid_kcal_is_rejected(kcal: float) -> None:
    with pytest.raises(ValueError, match="kcal"):
        generate_meal_plan(_request(kcal=kcal), LIBRARY)


@pytest.mark.parametrize("meals_per_day", [3, 4, 5])
@pytest.mark.parametrize("diet", DIETS)
def test_seed_library_fills_every_slot_every_day(meals_per_day: int, diet: str) -> None:
    req = _request(meals_per_day=meals_per_day, diet=diet, protein_g=100)
    plan = generate_meal_plan(req, LIBRARY)
    _check_invariants(plan, req, BY_ID)
    assert len(plan.days) == 7
    assert all(len(d.meals) == meals_per_day for d in plan.days)
    assert "meals/day" in plan.explanation


@pytest.mark.parametrize("meals_per_day", [3, 4, 5])
@pytest.mark.parametrize("diet", ["omnivore", "pescatarian"])
def test_seed_library_hits_a_typical_target_without_warnings(meals_per_day: int, diet: str) -> None:
    req = _request(meals_per_day=meals_per_day, diet=diet, protein_g=130)
    plan = generate_meal_plan(req, LIBRARY)
    assert plan.warnings == ()
    assert all(d.warning is None for d in plan.days)


@pytest.mark.parametrize(
    ("diet", "allergies"),
    [
        ("vegan", ()),
        ("vegetarian", ("lactose",)),
        ("pescatarian", ("fish", "shellfish")),
        ("omnivore", ("gluten", "lactose", "nuts", "eggs", "soy")),
    ],
)
def test_filters_hold_on_the_seed_library(diet: str, allergies: tuple[str, ...]) -> None:
    req = _request(diet=diet, allergies=allergies)
    plan = generate_meal_plan(req, LIBRARY)
    _check_invariants(plan, req, BY_ID)
    assert eligible_meals(LIBRARY, diet, allergies)


def test_eligible_meals_filters_and_sorts_by_id() -> None:
    meals = [
        MealCandidate("b", ("lunch",), ("vegan",), (), 500, 30),
        MealCandidate("a", ("lunch",), (), (), 500, 30),
        MealCandidate("c", ("lunch",), ("vegan",), ("nuts",), 500, 30),
    ]
    assert [m.id for m in eligible_meals(meals, "vegan", ())] == ["b", "c"]
    assert [m.id for m in eligible_meals(meals, "vegan", ("nuts",))] == ["b"]
    assert [m.id for m in eligible_meals(meals, "omnivore", ())] == ["a", "b", "c"]


def test_unreachable_protein_returns_the_best_attempt_with_the_spec_warning() -> None:
    req = _request(protein_g=600)
    plan = generate_meal_plan(req, LIBRARY)
    assert all(d.warning and MEAL_WARNING_PROTEIN in d.warning for d in plan.days)
    assert MEAL_WARNING_PROTEIN in plan.warnings
    _check_invariants(plan, req, BY_ID)


def test_unreachable_kcal_carries_a_warning() -> None:
    req = _request(kcal=9000, protein_g=100)
    plan = generate_meal_plan(req, LIBRARY)
    assert all(d.warning for d in plan.days)
    _check_invariants(plan, req, BY_ID)


def test_empty_library_gives_seven_empty_days_with_warnings() -> None:
    plan = generate_meal_plan(_request(), [])
    assert [d.weekday for d in plan.days] == list(WEEKDAYS)
    assert all(not d.meals and d.warning for d in plan.days)


def test_a_slot_without_enough_meals_is_left_out_with_a_warning_not_repeated() -> None:
    only = [MealCandidate("only", ("breakfast", "lunch", "dinner"), (), (), 700, 40)]
    req = _request(kcal=2100, protein_g=100, meals_per_day=3)
    plan = generate_meal_plan(req, only)
    used = sum(1 for d in plan.days for m in d.meals)
    assert used == MEAL_MAX_USES_PER_WEEK
    assert sum(1 for d in plan.days if d.warning) == 7
    _check_invariants(plan, req, {"only": only[0]})


def test_portion_factors_are_rounded_to_two_decimals() -> None:
    plan = generate_meal_plan(_request(), LIBRARY)
    for day in plan.days:
        for m in day.meals:
            assert m.portion_factor == round(m.portion_factor, 2)


def test_plan_seed_follows_user_and_week() -> None:
    assert plan_seed(10, 2026, 44) == plan_seed(10, 2026, 44)
    assert plan_seed(10, 2026, 44) != plan_seed(10, 2026, 45)
    assert plan_seed(10, 2026, 44) != plan_seed(11, 2026, 44)


def test_different_seeds_can_give_different_plans() -> None:
    plans = {
        tuple(
            m.meal_id for d in generate_meal_plan(_request(seed=s), LIBRARY).days for m in d.meals
        )
        for s in range(5)
    }
    assert len(plans) > 1


def test_totals_match_the_listed_meals() -> None:
    plan = generate_meal_plan(_request(), LIBRARY)
    for day in plan.days:
        assert day.total_kcal == sum(m.kcal for m in day.meals)
        for m in day.meals:
            assert m.kcal == round(BY_ID[m.meal_id].kcal * m.portion_factor)


# ───────────── property tests ─────────────

requests = st.builds(
    MealPlanRequest,
    kcal=st.integers(1200, 4500),
    protein_g=st.integers(60, 300),
    meals_per_day=st.sampled_from([3, 4, 5]),
    diet=st.sampled_from(DIETS),
    allergies=st.lists(st.sampled_from(ALLERGENS), unique=True, max_size=4).map(tuple),
    seed=st.integers(0, 2**63),
)

synthetic_meals = st.lists(
    st.builds(
        MealCandidate,
        id=st.uuids().map(str),
        slots=st.lists(
            st.sampled_from(["breakfast", "lunch", "dinner", "snack"]),
            min_size=1,
            max_size=4,
            unique=True,
        ),
        diet_tags=st.lists(
            st.sampled_from(["vegetarian", "vegan", "pescatarian"]), unique=True, max_size=3
        ),
        allergens=st.lists(st.sampled_from(ALLERGENS), unique=True, max_size=3),
        kcal=st.integers(80, 1500),
        protein_g=st.integers(0, 120),
    ),
    max_size=40,
    unique_by=lambda m: m.id,
)


@settings(max_examples=150, deadline=None)
@given(req=requests)
def test_f7_1_f7_2_f7_3_on_the_seed_library(req: MealPlanRequest) -> None:
    """F7.1 each day on target or warned, F7.2 at most twice a week, F7.3 filters respected."""
    _check_invariants(generate_meal_plan(req, LIBRARY), req, BY_ID)


@settings(max_examples=150, deadline=None)
@given(req=requests, meals=synthetic_meals)
def test_f7_1_f7_2_f7_3_on_random_libraries(
    req: MealPlanRequest, meals: list[MealCandidate]
) -> None:
    _check_invariants(generate_meal_plan(req, meals), req, {m.id: m for m in meals})


@settings(max_examples=60, deadline=None)
@given(req=requests, meals=synthetic_meals)
def test_f7_4_same_inputs_and_seed_give_the_same_plan(
    req: MealPlanRequest, meals: list[MealCandidate]
) -> None:
    first = generate_meal_plan(req, meals)
    assert generate_meal_plan(req, meals) == first
    assert generate_meal_plan(req, list(reversed(meals))) == first


def test_f7_4_snapshot_is_stable() -> None:
    """A fixed request gives a fixed plan across runs (the generator has its own PRNG)."""
    plan = generate_meal_plan(_request(seed=123), LIBRARY)
    again = generate_meal_plan(_request(seed=123), list(reversed(LIBRARY)))
    assert plan == again
