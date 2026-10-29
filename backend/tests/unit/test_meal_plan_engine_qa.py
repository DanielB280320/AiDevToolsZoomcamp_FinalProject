"""QA for #36 (PR #145): the custom PRNG is the reference SplitMix64 (so F7.4 holds on every
platform), the seed folds in the ISO year, and a fixed request gives a pinned plan."""

from app.engines.meal_plan import (
    MealCandidate,
    MealPlanRequest,
    _Rng,
    generate_meal_plan,
    plan_seed,
)

# Reference SplitMix64 outputs for seed 0 (Vigna's splitmix64.c).
SPLITMIX64_SEED0 = (0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F)


def test_rng_is_reference_splitmix64() -> None:
    rng = _Rng(0)
    for expected in SPLITMIX64_SEED0:
        assert rng.next_float() == (expected >> 11) / float(1 << 53)


def test_rng_floats_are_in_unit_interval() -> None:
    rng = _Rng(2**64 - 1)
    values = [rng.next_float() for _ in range(1000)]
    assert all(0.0 <= v < 1.0 for v in values)


def test_seed_differs_across_iso_years_and_weeks() -> None:
    uid = 0x1234_5678_9ABC_DEF0_1234_5678_9ABC_DEF0
    seeds = {plan_seed(uid, year, week) for year in (2026, 2027, 2028) for week in range(1, 54)}
    assert len(seeds) == 3 * 53
    assert 0 <= plan_seed(uid, 2026, 1) < 2**64


def test_pinned_plan_for_a_fixed_request() -> None:
    """Same inputs + seed -> same plan, pinned to literal values (not just run twice)."""
    meals = [
        MealCandidate(f"m{i}", ("breakfast", "lunch", "dinner"), (), (), 500 + 40 * i, 30 + i)
        for i in range(8)
    ]
    req = MealPlanRequest(kcal=2000, protein_g=100, meals_per_day=3, diet="omnivore", seed=42)
    plan = generate_meal_plan(req, meals)
    again = generate_meal_plan(req, list(reversed(meals)))
    assert plan == again
    first_day = [(m.slot, m.meal_id, m.portion_factor) for m in plan.days[0].meals]
    # 502 + 702 + 799 = 2003 kcal, within +-5 % of 2000.
    assert first_day == [("breakfast", "m3", 0.81), ("lunch", "m1", 1.3), ("dinner", "m4", 1.21)]
    assert plan.days[0].warning is None
