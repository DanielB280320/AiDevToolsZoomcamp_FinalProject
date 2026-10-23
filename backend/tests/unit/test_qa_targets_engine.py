"""QA (#21 / PR #88): independent oracle checks for the F3 targets engine.

The oracle below is written from docs/spec.md F3.1 to F3.6 and D47 only. It keeps every
intermediate value at full precision and rounds half-up only at output (kcal to 1, grams to
0.1 g). It does not import any engine helper, so a shared bug in the engine's rounding helpers
can't hide here.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.targets import Goal, Lifestyle, Sex, compute_targets, navy_body_fat

_S = {"male": 5, "female": -161, "unspecified": -78}
_FACTOR = {"sedentary": 1.20, "lightly_active": 1.30, "active": 1.45, "very_active": 1.60}
_ADJ = {
    "cutting": -0.20,
    "recomposition": -0.10,
    "muscle_gain": 0.10,
    "maintenance": 0.0,
    "wellness": 0.0,
}
_PROTEIN = {
    "cutting": 2.2,
    "recomposition": 2.2,
    "muscle_gain": 1.8,
    "maintenance": 1.6,
    "wellness": 1.4,
}
_FLOOR = {"male": 1500, "female": 1200, "unspecified": 1350}


def _half_up(value: float, quantum: str = "1") -> Decimal:
    return Decimal(repr(value)).quantize(Decimal(quantum), rounding=ROUND_HALF_UP)


def _oracle(
    sex: str,
    weight: float,
    height: float,
    age: float,
    bf: float | None,
    lifestyle: str,
    goal: str,
    weekly: float,
) -> dict[str, Any]:
    if bf is not None:
        bmr = 370 + 21.6 * weight * (1 - bf / 100)
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age + _S[sex]
    baseline = bmr * _FACTOR[lifestyle]
    per_day = weekly / 7
    computed = int(_half_up((baseline + per_day) * (1 + _ADJ[goal])))
    kcal = max(computed, _FLOOR[sex])
    protein = float(_half_up(_PROTEIN[goal] * weight, "0.1"))
    fat = float(_half_up(max(0.25 * kcal / 9, 0.6 * weight), "0.1"))
    rest = kcal - 4 * protein - 9 * fat
    carbs = 0.0 if rest < 0 else float(_half_up(rest / 4, "0.1"))
    baseline_kcal = int(_half_up(baseline))
    per_day_kcal = int(_half_up(per_day))
    return {
        "bmr_kcal": int(_half_up(bmr)),
        "baseline_kcal": baseline_kcal,
        "planned_exercise_kcal_per_day": per_day_kcal,
        "kcal": kcal,
        "floor_applied": computed < _FLOOR[sex],
        "protein_g": protein,
        "fat_g": fat,
        "carbs_g": carbs,
        "carbs_clamped": rest < 0,
        "target_balance_kcal": kcal - (baseline_kcal + per_day_kcal),
    }


def test_qa_targets_ana_rounds_only_at_output() -> None:
    # Chained rounding (BMR 1385 → 1385 × 1.3 = 1800.5 → 1801 → (1801 + 94) × 0.8 = 1516)
    # would contradict the contract example; output-only rounding gives 1800 / 1515.
    assert int(_half_up(1385 * 1.3)) == 1801
    r = compute_targets(
        sex=Sex.FEMALE,
        weight_kg=72.5,
        height_cm=165,
        age_years=35,
        body_fat_pct=35.2,
        lifestyle=Lifestyle.LIGHTLY_ACTIVE,
        goal=Goal.CUTTING,
        planned_exercise_kcal_per_week=658,
    )
    assert (r.bmr_kcal, r.baseline_kcal, r.kcal) == (1385, 1800, 1515)
    assert (r.protein_g, r.fat_g, r.carbs_g, r.target_balance_kcal) == (159.5, 43.5, 121.4, -379)


def test_qa_female_45kg_floor_case() -> None:
    r = compute_targets(
        sex=Sex.FEMALE,
        weight_kg=45,
        height_cm=155,
        age_years=60,
        body_fat_pct=None,
        lifestyle=Lifestyle.SEDENTARY,
        goal=Goal.CUTTING,
        planned_exercise_kcal_per_week=0,
    )
    assert (r.kcal, r.floor_applied, r.floor_kcal) == (1200, True, 1200)
    assert "919 kcal is below the 1200 kcal minimum" in r.explanation


@given(
    sex=st.sampled_from(list(Sex)),
    weight=st.floats(min_value=35, max_value=300),
    height=st.floats(min_value=120, max_value=230),
    # Spec sets no upper age; F1.1 sets 18 as the minimum. Go beyond the engineer's 14-100.
    age=st.floats(min_value=18, max_value=120),
    bf=st.one_of(st.none(), st.floats(min_value=3, max_value=60)),
    lifestyle=st.sampled_from(list(Lifestyle)),
    goal=st.sampled_from(list(Goal)),
    weekly=st.floats(min_value=0, max_value=7000),
)
@settings(max_examples=400, deadline=None)
def test_qa_engine_matches_independent_spec_oracle(
    sex: Sex,
    weight: float,
    height: float,
    age: float,
    bf: float | None,
    lifestyle: Lifestyle,
    goal: Goal,
    weekly: float,
) -> None:
    r = compute_targets(
        sex=sex,
        weight_kg=weight,
        height_cm=height,
        age_years=age,
        body_fat_pct=bf,
        lifestyle=lifestyle,
        goal=goal,
        planned_exercise_kcal_per_week=weekly,
    )
    expected = _oracle(sex.value, weight, height, age, bf, lifestyle.value, goal.value, weekly)
    for name, value in expected.items():
        assert getattr(r, name) == value, name
    assert r.kcal >= _FLOOR[sex.value]


def test_qa_weekly_float_is_not_pre_rounded() -> None:
    # Male 80/180/30 sedentary: baseline 2136. 3.5 kcal/week = 0.5/day.
    base: dict[str, Any] = {
        "sex": Sex.MALE,
        "weight_kg": 80.0,
        "height_cm": 180.0,
        "age_years": 30.0,
        "body_fat_pct": None,
        "lifestyle": Lifestyle.SEDENTARY,
    }
    # Muscle gain: (2136 + 3.5/7 = 0.5) × 1.1 = 2350.15 → 2350; pre-rounding 0.5 → 1 gives
    # 2137 × 1.1 = 2350.7 → 2351.
    r = compute_targets(**base, goal=Goal.MUSCLE_GAIN, planned_exercise_kcal_per_week=3.5)
    assert r.kcal == 2350
    assert r.planned_exercise_kcal_per_day == 1


def test_qa_navy_returns_unrounded_value() -> None:
    r = navy_body_fat(Sex.MALE, 180, 38, 85)
    assert r.body_fat_pct != round(r.body_fat_pct, 1)
    assert math.isclose(r.body_fat_pct, 16.1066, abs_tol=1e-3)


def test_qa_navy_out_of_range_is_returned_not_raised() -> None:
    # Range policy is deferred to #25 (owner question). Today the engine returns the value,
    # and compute_targets rejects body fat outside [0, 100) so a bad estimate can't produce
    # a Katch-McArdle BMR silently.
    low = navy_body_fat(Sex.MALE, 180, 40, 41).body_fat_pct
    assert low < 0
    high = navy_body_fat(Sex.FEMALE, 150, 20, 200, 200).body_fat_pct
    assert high > 60
    for bf in (low, 100.0):
        with pytest.raises(ValueError):
            compute_targets(
                sex=Sex.MALE,
                weight_kg=80,
                height_cm=180,
                age_years=30,
                body_fat_pct=bf,
                lifestyle=Lifestyle.SEDENTARY,
                goal=Goal.MAINTENANCE,
                planned_exercise_kcal_per_week=0,
            )
