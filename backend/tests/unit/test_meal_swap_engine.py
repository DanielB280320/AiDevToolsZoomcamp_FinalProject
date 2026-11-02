"""D86 meal swap engine: table-driven rules (one per filter) and property tests on random libraries
and on the real seed library."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.constants import (
    MEAL_MAX_USES_PER_WEEK,
    MEAL_PORTION_MAX,
    MEAL_PORTION_MIN,
    SWAP_KCAL_BAND,
    SWAP_MAX_ALTERNATIVES,
)
from app.engines.meal_plan import MealCandidate
from app.engines.meal_swap import SwapRequest, suggest_swaps
from tests.unit.test_meal_plan_engine import LIBRARY


def meal(
    id: str,
    kcal: float,
    slots: tuple[str, ...] = ("lunch",),
    diet_tags: tuple[str, ...] = (),
    allergens: tuple[str, ...] = (),
) -> MealCandidate:
    return MealCandidate(id, slots, diet_tags, allergens, kcal, kcal / 20, kcal / 10, kcal / 30)


def ids(request: SwapRequest, meals: list[MealCandidate]) -> list[str]:
    return [a.meal_id for a in suggest_swaps(request, meals).alternatives]


def req(**kw: object) -> SwapRequest:
    base: dict[str, object] = {"slot": "lunch", "planned_kcal": 600.0, "diet": "omnivore"}
    return SwapRequest(**{**base, **kw})  # type: ignore[arg-type]


# ───────────── table-driven rules ─────────────


@pytest.mark.parametrize(
    ("kcal", "qualifies"),
    [
        (600, True),
        (540, True),  # exactly -10 %
        (660, True),  # exactly +10 %
        (539, True),  # 539 * 1.1 = 592.9 -> the portion factor rescales it into the band
        (661, True),
        (300, False),  # 300 * 1.5 = 450 < 540
        (900, False),  # 900 * 0.75 = 675 > 660
        (400, True),  # 400 * 1.5 = 600
        (800, True),  # 800 * 0.75 = 600
    ],
)
def test_the_band_applies_after_the_portion_rescale(kcal: int, qualifies: bool) -> None:
    assert (ids(req(), [meal("a", kcal)]) == ["a"]) is qualifies


def test_the_portion_factor_matches_the_planned_kcal_and_is_clamped() -> None:
    result = suggest_swaps(req(), [meal("a", 500), meal("b", 850), meal("c", 400)])
    by_id = {a.meal_id: a for a in result.alternatives}
    assert by_id["a"].portion_factor == 1.2 and by_id["a"].kcal == 600
    assert by_id["b"].portion_factor == MEAL_PORTION_MIN and by_id["b"].kcal == 638
    assert by_id["c"].portion_factor == MEAL_PORTION_MAX and by_id["c"].kcal == 600


def test_filter_slot() -> None:
    meals = [meal("a", 600, ("dinner",)), meal("b", 600, ("lunch", "dinner"))]
    assert ids(req(), meals) == ["b"]


@pytest.mark.parametrize(
    ("diet", "expected"),
    [("omnivore", ["a", "b", "c"]), ("vegetarian", ["b", "c"]), ("vegan", ["c"])],
)
def test_filter_diet(diet: str, expected: list[str]) -> None:
    meals = [
        meal("a", 600),
        meal("b", 600, diet_tags=("vegetarian",)),
        meal("c", 600, diet_tags=("vegetarian", "vegan")),
    ]
    assert ids(req(diet=diet), meals) == expected


def test_filter_allergies() -> None:
    meals = [
        meal("a", 600, allergens=("nuts",)),
        meal("b", 600, allergens=("eggs",)),
        meal("c", 600),
    ]
    assert ids(req(allergies=("nuts",)), meals) == ["b", "c"]
    assert ids(req(allergies=("nuts", "eggs")), meals) == ["c"]


def test_meals_used_twice_that_week_are_excluded() -> None:
    meals = [meal("a", 600), meal("b", 600), meal("c", 600)]
    uses = {"a": MEAL_MAX_USES_PER_WEEK, "b": MEAL_MAX_USES_PER_WEEK - 1, "c": 7}
    assert ids(req(week_uses=uses), meals) == ["b"]


def test_meals_already_in_the_day_are_excluded() -> None:
    meals = [meal("a", 600), meal("b", 600), meal("c", 600)]
    assert ids(req(day_meal_ids=("a", "c")), meals) == ["b"]


def test_closest_kcal_first_ties_by_id_and_at_most_three() -> None:
    # Meals the rescale can bring exactly onto 600 kcal all tie at distance 0 and sort by id; the
    # others are clamped at 0.75x or 1.5x and sort by how far they end up.
    meals = [
        meal("f", 600),
        meal("e", 750),  # 0.8x -> on target
        meal("d", 820),  # 0.75x -> 615
        meal("c", 850),  # 0.75x -> 637.5
        meal("b", 400),  # 1.5x -> on target
        meal("a", 870),  # 0.75x -> 652.5
    ]
    result = suggest_swaps(req(), meals)
    assert [a.meal_id for a in result.alternatives] == ["b", "e", "f"]
    assert len(result.alternatives) == SWAP_MAX_ALTERNATIVES
    far = suggest_swaps(req(), [m for m in meals if m.id in "acd"])
    assert [a.meal_id for a in far.alternatives] == ["d", "c", "a"]


def test_fewer_than_three_are_returned_as_is_and_empty_is_valid() -> None:
    one = suggest_swaps(req(), [meal("a", 610), meal("b", 2000)])
    assert [a.meal_id for a in one.alternatives] == ["a"]
    assert "1 of 1" in one.reason
    none = suggest_swaps(req(), [meal("b", 2000)])
    assert none.alternatives == () and none.reason
    assert suggest_swaps(req(), []).alternatives == ()


def test_input_order_does_not_matter() -> None:
    meals = [meal(c, 600 + i) for i, c in enumerate("fedcba")]
    assert ids(req(), meals) == ids(req(), list(reversed(meals)))


def test_macros_are_scaled_by_the_portion() -> None:
    (alt,) = suggest_swaps(req(), [meal("a", 500)]).alternatives
    assert alt.portion_factor == 1.2
    assert (alt.protein_g, alt.carbs_g, alt.fat_g) == (30.0, 60.0, 20.0)


@pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), float("inf")])
def test_invalid_planned_kcal_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="planned_kcal"):
        suggest_swaps(req(planned_kcal=bad), [])


# ───────────── property tests ─────────────

candidates = st.lists(
    st.builds(
        MealCandidate,
        id=st.text("abcdefghij", min_size=1, max_size=3),
        slots=st.lists(st.sampled_from(["breakfast", "lunch", "dinner", "snack"]), min_size=1).map(
            tuple
        ),
        diet_tags=st.sets(st.sampled_from(["vegetarian", "vegan", "pescatarian"])).map(tuple),
        allergens=st.sets(st.sampled_from(["nuts", "eggs", "soy"])).map(tuple),
        kcal=st.floats(50, 2500),
        protein_g=st.floats(0, 100),
        carbs_g=st.floats(0, 200),
        fat_g=st.floats(0, 100),
    ),
    max_size=40,
    unique_by=lambda m: m.id,
)
requests = st.builds(
    SwapRequest,
    slot=st.sampled_from(["breakfast", "lunch", "dinner", "snack"]),
    planned_kcal=st.floats(50, 2500),
    diet=st.sampled_from(["omnivore", "vegetarian", "vegan", "pescatarian"]),
    allergies=st.sets(st.sampled_from(["nuts", "eggs", "soy"])).map(tuple),
    day_meal_ids=st.sets(st.text("abcdefghij", min_size=1, max_size=3)).map(tuple),
    week_uses=st.dictionaries(st.text("abcdefghij", min_size=1, max_size=3), st.integers(0, 3)),
)


@settings(max_examples=300, deadline=None)
@given(request=requests, meals=candidates)
def test_property_every_alternative_is_in_band_and_respects_the_filters(
    request: SwapRequest, meals: list[MealCandidate]
) -> None:
    result = suggest_swaps(request, meals)
    by_id = {m.id: m for m in meals}
    assert len(result.alternatives) <= SWAP_MAX_ALTERNATIVES
    assert result.reason
    seen = set()
    for alt in result.alternatives:
        m = by_id[alt.meal_id]
        assert MEAL_PORTION_MIN <= alt.portion_factor <= MEAL_PORTION_MAX
        assert abs(m.kcal * alt.portion_factor - request.planned_kcal) <= (
            SWAP_KCAL_BAND * request.planned_kcal + 1e-9
        )
        assert abs(alt.kcal - m.kcal * alt.portion_factor) <= 0.5 + 1e-9
        assert request.slot in m.slots
        assert alt.meal_id not in request.day_meal_ids
        assert (request.week_uses or {}).get(alt.meal_id, 0) < MEAL_MAX_USES_PER_WEEK
        assert request.diet == "omnivore" or request.diet in m.diet_tags
        assert not set(request.allergies) & set(m.allergens)
        assert alt.meal_id not in seen
        seen.add(alt.meal_id)


@settings(max_examples=200, deadline=None)
@given(request=requests, meals=candidates)
def test_property_order_is_closest_first_and_deterministic(
    request: SwapRequest, meals: list[MealCandidate]
) -> None:
    first = suggest_swaps(request, meals)
    assert first == suggest_swaps(request, list(reversed(meals)))
    by_id = {m.id: m for m in meals}
    keys = [
        (abs(by_id[a.meal_id].kcal * a.portion_factor - request.planned_kcal), a.meal_id)
        for a in first.alternatives
    ]
    assert keys == sorted(keys)


@settings(max_examples=100, deadline=None)
@given(
    planned=st.floats(150, 1500),
    slot=st.sampled_from(["breakfast", "lunch", "dinner", "snack"]),
    diet=st.sampled_from(["omnivore", "vegetarian", "vegan", "pescatarian"]),
)
def test_property_on_the_seed_library(planned: float, slot: str, diet: str) -> None:
    result = suggest_swaps(SwapRequest(slot=slot, planned_kcal=planned, diet=diet), LIBRARY)
    by_id = {m.id: m for m in LIBRARY}
    for alt in result.alternatives:
        assert (
            abs(by_id[alt.meal_id].kcal * alt.portion_factor - planned)
            <= SWAP_KCAL_BAND * planned + 1e-9
        )
