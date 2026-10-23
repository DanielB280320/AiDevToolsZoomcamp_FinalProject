"""F3 targets engine (#21): table-driven reference cases and Hypothesis properties.

Reference values are hand-computed from the published equations:
- Mifflin-St Jeor: Mifflin MD, St Jeor ST, et al. "A new predictive equation for resting energy
  expenditure in healthy individuals." Am J Clin Nutr 1990;51(2):241-247.
- Katch-McArdle: McArdle WD, Katch FI, Katch VL. Exercise Physiology: Nutrition, Energy, and
  Human Performance (BMR = 370 + 21.6 x LBM).
- US Navy circumference method: Hodgdon JA, Beckett MB. "Prediction of percent body fat for U.S.
  Navy men/women from body circumferences and height." Naval Health Research Center reports
  84-11 / 84-29, 1984 (metric form as in spec F3.3).
"""

from __future__ import annotations

import dataclasses
import math
import re
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines import constants as c
from app.engines.targets import (
    BmrFormula,
    Goal,
    Lifestyle,
    Sex,
    TargetsResult,
    compute_bmr,
    compute_targets,
    katch_mcardle_bmr,
    mifflin_st_jeor_bmr,
    navy_body_fat,
    round_grams,
    round_kcal,
)
from tests.contract import assert_matches_schema, contract

KCAL_TOL = 1
BF_TOL = 0.5


def _targets(**overrides: Any) -> TargetsResult:
    args: dict[str, Any] = {
        "sex": Sex.MALE,
        "weight_kg": 80.0,
        "height_cm": 180.0,
        "age_years": 30.0,
        "body_fat_pct": None,
        "lifestyle": Lifestyle.SEDENTARY,
        "goal": Goal.MAINTENANCE,
        "planned_exercise_kcal_per_week": 0.0,
    }
    args.update(overrides)
    return compute_targets(**args)


# ─────────────────────────────── output shape ───────────────────────────────

TARGETS_COMPUTED_FIELDS = {
    "bmr_formula",
    "bmr_kcal",
    "lifestyle_factor",
    "baseline_kcal",
    "planned_exercise_kcal_per_day",
    "goal_adjustment_pct",
    "kcal",
    "protein_g",
    "carbs_g",
    "fat_g",
    "target_balance_kcal",
    "floor_applied",
    "floor_kcal",
    "carbs_clamped",
    "weight_used_kg",
    "body_fat_pct_used",
    "explanation",
    "inputs",
}


def test_result_has_every_computed_field_of_the_contract_targets_schema() -> None:
    schema = contract()["components"]["schemas"]["Targets"]
    persisted_only = {"id", "athlete_id", "valid_from", "estimated", "created_at"}
    assert set(schema["required"]) - persisted_only == TARGETS_COMPUTED_FIELDS
    assert {f.name for f in dataclasses.fields(TargetsResult)} == TARGETS_COMPUTED_FIELDS


def _as_payload(r: TargetsResult) -> dict[str, Any]:
    payload = dataclasses.asdict(r)
    payload["bmr_formula"] = r.bmr_formula.value
    payload.update(
        id="5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d",
        athlete_id="3f0b6a1e-6a55-4f3c-9a43-1c2a3a4b5c6d",
        valid_from="2026-10-21",
        estimated=True,
        created_at="2026-10-21T18:05:00Z",
    )
    return payload


@pytest.mark.parametrize("bf", [None, 35.2])
def test_result_validates_against_contract_targets_schema(bf: float | None) -> None:
    r = _targets(body_fat_pct=bf, planned_exercise_kcal_per_week=658)
    assert_matches_schema(_as_payload(r), "Targets")


def test_kcal_fields_are_integers_and_grams_are_numbers() -> None:
    r = _targets(planned_exercise_kcal_per_week=1234.5, body_fat_pct=21.3)
    for name in (
        "bmr_kcal",
        "baseline_kcal",
        "planned_exercise_kcal_per_day",
        "kcal",
        "target_balance_kcal",
        "floor_kcal",
    ):
        assert type(getattr(r, name)) is int, name
    for name in ("protein_g", "carbs_g", "fat_g"):
        assert isinstance(getattr(r, name), float), name
    assert r.bmr_formula in ("katch_mcardle", "mifflin_st_jeor")


# ─────────────────────────────── F3.1 reference cases ───────────────────────────────


@pytest.mark.parametrize(
    ("sex", "weight", "height", "age", "expected"),
    [
        # Issue #21 reference cases.
        (Sex.MALE, 80, 180, 30, 1780),  # 800 + 1125 − 150 + 5
        (Sex.FEMALE, 60, 165, 30, 1320),  # 600 + 1031.25 − 150 − 161 = 1320.25
        (Sex.UNSPECIFIED, 70, 170, 40, 1485),  # 700 + 1062.5 − 200 − 78 = 1484.5
        # Published equation (Mifflin et al. 1990), worked by hand:
        (Sex.MALE, 90, 175, 45, 1774),  # 900 + 1093.75 − 225 + 5 = 1773.75
        (Sex.FEMALE, 55, 160, 25, 1264),  # 550 + 1000 − 125 − 161 = 1264
    ],
)
def test_mifflin_st_jeor_reference_cases(
    sex: Sex, weight: float, height: float, age: float, expected: int
) -> None:
    r = mifflin_st_jeor_bmr(sex, weight, height, age)
    assert r.formula is BmrFormula.MIFFLIN_ST_JEOR
    assert abs(r.bmr - expected) <= KCAL_TOL
    assert "Mifflin-St Jeor" in r.explanation


@pytest.mark.parametrize(
    ("weight", "bf", "expected"),
    [
        # Published equation (McArdle, Katch & Katch), worked by hand:
        (80, 20, 1752),  # LBM 64 kg → 370 + 21.6 × 64 = 1752.4
        (100, 30, 1882),  # LBM 70 kg → 370 + 1512 = 1882
        (72.5, 35.2, 1385),  # TargetsAna: LBM 46.98 kg → 1384.77
    ],
)
def test_katch_mcardle_reference_cases(weight: float, bf: float, expected: int) -> None:
    r = katch_mcardle_bmr(weight, bf)
    assert r.formula is BmrFormula.KATCH_MCARDLE
    assert abs(r.bmr - expected) <= KCAL_TOL
    assert "Katch-McArdle" in r.explanation


def test_targets_ana_contract_example() -> None:
    """openapi.yaml components.examples.TargetsAna."""
    r = _targets(
        sex=Sex.FEMALE,
        weight_kg=72.5,
        height_cm=165,
        age_years=35,
        body_fat_pct=35.2,
        lifestyle=Lifestyle.LIGHTLY_ACTIVE,
        goal=Goal.CUTTING,
        planned_exercise_kcal_per_week=658,
    )
    assert r.bmr_formula == "katch_mcardle"
    assert r.bmr_kcal == 1385
    assert r.lifestyle_factor == 1.3
    assert r.baseline_kcal == 1800
    assert r.planned_exercise_kcal_per_day == 94
    assert r.goal_adjustment_pct == -20
    assert r.kcal == 1515
    assert r.protein_g == 159.5
    assert r.fat_g == 43.5
    assert r.carbs_g == 121.4
    assert r.target_balance_kcal == -379
    assert r.floor_applied is False
    assert r.floor_kcal == 1200
    assert r.carbs_clamped is False
    assert r.weight_used_kg == 72.5
    assert r.body_fat_pct_used == 35.2
    assert r.inputs["weight_kg"] == 72.5
    assert r.inputs["body_fat_pct"] == 35.2
    assert r.inputs["lifestyle"] == "lightly_active"
    assert r.inputs["goal"] == "cutting"
    assert r.inputs["planned_exercise_kcal_per_week"] == 658


def test_targets_ana_matches_contract_example_values() -> None:
    example = contract()["components"]["examples"]["TargetsAna"]["value"]
    r = _targets(
        sex=Sex.FEMALE,
        weight_kg=72.5,
        height_cm=165,
        age_years=35,
        body_fat_pct=35.2,
        lifestyle=Lifestyle.LIGHTLY_ACTIVE,
        goal=Goal.CUTTING,
        planned_exercise_kcal_per_week=658,
    )
    for name in TARGETS_COMPUTED_FIELDS - {"explanation", "inputs"}:
        assert getattr(r, name) == example[name], name


@pytest.mark.parametrize(
    ("sex", "height", "neck", "waist", "hip", "expected"),
    [
        # Issue #21 reference cases.
        (Sex.MALE, 180, 38, 85, None, 16.1),
        (Sex.FEMALE, 165, 32, 70, 95, 24.9),
        (Sex.UNSPECIFIED, 165, 32, 70, 95, 24.9),
        # Hodgdon & Beckett 1984 equations, worked by hand:
        # male: 495 / (1.0324 − 0.19077·log10(60) + 0.15456·log10(175)) − 450 = 26.0
        (Sex.MALE, 175, 40, 100, None, 26.0),
        # female: 495 / (1.29579 − 0.35004·log10(156) + 0.221·log10(165)) − 450 = 36.2
        (Sex.FEMALE, 165, 34, 90, 100, 36.2),
    ],
)
def test_navy_reference_cases(
    sex: Sex, height: float, neck: float, waist: float, hip: float | None, expected: float
) -> None:
    r = navy_body_fat(sex, height, neck, waist, hip)
    assert abs(r.body_fat_pct - expected) <= BF_TOL
    assert "Navy" in r.explanation
    assert f"{r.body_fat_pct:.1f}" in r.explanation


# ─────────────────────────────── Navy domain ───────────────────────────────


@pytest.mark.parametrize(
    ("sex", "height", "neck", "waist", "hip", "message"),
    [
        (Sex.MALE, 180, 40, 40, None, "waist larger than the neck"),
        (Sex.MALE, 180, 45, 40, None, "waist larger than the neck"),
        (Sex.FEMALE, 165, 200, 70, 95, "waist + hip larger than the neck"),
        (Sex.UNSPECIFIED, 165, 165, 70, 95, "waist + hip larger than the neck"),
        (Sex.FEMALE, 165, 32, 70, None, "needs a hip measurement"),
        (Sex.MALE, 0, 38, 85, None, "height_cm must be a positive"),
        (Sex.MALE, 180, 38, math.nan, None, "waist_cm must be a positive"),
        (Sex.FEMALE, 180, 38, 85, math.inf, "hip_cm must be a positive"),
        # log argument so large the denominator reaches 0 → undefined, never NaN/inf.
        (Sex.MALE, 1, 1, 1e300, None, "undefined"),
    ],
)
def test_navy_domain_raises_readable_value_error(
    sex: Sex, height: float, neck: float, waist: float, hip: float | None, message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        navy_body_fat(sex, height, neck, waist, hip)


@given(
    sex=st.sampled_from(list(Sex)),
    height=st.floats(min_value=1, max_value=1e6),
    neck=st.floats(min_value=1, max_value=1e6),
    waist=st.floats(min_value=1, max_value=1e6),
    hip=st.floats(min_value=1, max_value=1e6),
)
def test_navy_never_returns_nan_or_infinity(
    sex: Sex, height: float, neck: float, waist: float, hip: float
) -> None:
    try:
        r = navy_body_fat(sex, height, neck, waist, hip)
    except ValueError:
        return
    assert math.isfinite(r.body_fat_pct)


# ─────────────────────────────── F3.2 ───────────────────────────────

ranges = {
    "height_cm": st.floats(min_value=120, max_value=230),
    "weight_kg": st.floats(min_value=35, max_value=300),
    "age_years": st.integers(min_value=14, max_value=100),
    "body_fat_pct": st.floats(min_value=3, max_value=60),
    "exercise": st.floats(min_value=0, max_value=7000),
}


@given(
    sex=st.sampled_from(list(Sex)),
    weight=ranges["weight_kg"],
    height=ranges["height_cm"],
    age=ranges["age_years"],
    bf=st.one_of(st.none(), ranges["body_fat_pct"]),
)
def test_katch_mcardle_iff_body_fat_given(
    sex: Sex, weight: float, height: float, age: int, bf: float | None
) -> None:
    r = compute_bmr(sex, weight, height, age, bf)
    expected = BmrFormula.KATCH_MCARDLE if bf is not None else BmrFormula.MIFFLIN_ST_JEOR
    assert r.formula is expected
    t = _targets(sex=sex, weight_kg=weight, height_cm=height, age_years=age, body_fat_pct=bf)
    assert t.bmr_formula is expected
    assert t.body_fat_pct_used == bf


@pytest.mark.parametrize(
    ("lifestyle", "factor"),
    [
        (Lifestyle.SEDENTARY, 1.20),
        (Lifestyle.LIGHTLY_ACTIVE, 1.30),
        (Lifestyle.ACTIVE, 1.45),
        (Lifestyle.VERY_ACTIVE, 1.60),
    ],
)
def test_lifestyle_factor(lifestyle: Lifestyle, factor: float) -> None:
    r = _targets(lifestyle=lifestyle)
    assert r.lifestyle_factor == factor
    assert r.baseline_kcal == round_kcal(1780 * factor)
    assert f"{factor:.2f}" in r.explanation


# ─────────────────────────────── F3.4 ───────────────────────────────


@pytest.mark.parametrize(
    ("goal", "adjustment_pct", "protein_g_per_kg"),
    [
        (Goal.CUTTING, -20, 2.2),
        (Goal.RECOMPOSITION, -10, 2.2),
        (Goal.MUSCLE_GAIN, 10, 1.8),
        (Goal.MAINTENANCE, 0, 1.6),
        (Goal.WELLNESS, 0, 1.4),
    ],
)
def test_goal_adjustment_and_protein(
    goal: Goal, adjustment_pct: float, protein_g_per_kg: float
) -> None:
    # Male 80 kg / 180 cm / 30 y, sedentary, 1400 kcal/week planned (200/day):
    # baseline 1780 × 1.2 = 2136; (2136 + 200) × (1 + adj).
    r = _targets(goal=goal, planned_exercise_kcal_per_week=1400)
    assert r.goal_adjustment_pct == adjustment_pct
    assert r.planned_exercise_kcal_per_day == 200
    assert r.kcal == round_kcal(2336 * (1 + adjustment_pct / 100))
    assert r.protein_g == round_grams(protein_g_per_kg * 80)
    assert f"{protein_g_per_kg:g} g/kg" in r.explanation


def test_planned_exercise_is_weekly_divided_by_seven() -> None:
    r = _targets(planned_exercise_kcal_per_week=700)
    assert r.planned_exercise_kcal_per_day == 100
    assert r.kcal == 2136 + 100


# ─────────────────────────────── F3.6 floor ───────────────────────────────


def test_floor_applied_female_case() -> None:
    # BMR 957.75 → baseline 1149.3 → × 0.8 = 919.44 → floor 1200.
    r = _targets(
        sex=Sex.FEMALE,
        weight_kg=45,
        height_cm=155,
        age_years=60,
        lifestyle=Lifestyle.SEDENTARY,
        goal=Goal.CUTTING,
    )
    assert r.kcal == 1200
    assert r.floor_applied is True
    assert r.floor_kcal == 1200
    assert "919" in r.explanation
    assert "floor" in r.explanation.lower()
    assert "1200 kcal minimum" in r.explanation


@pytest.mark.parametrize(
    ("sex", "floor"), [(Sex.MALE, 1500), (Sex.FEMALE, 1200), (Sex.UNSPECIFIED, 1350)]
)
def test_floor_kcal_always_reported_for_sex(sex: Sex, floor: int) -> None:
    high = _targets(sex=sex, goal=Goal.MUSCLE_GAIN, lifestyle=Lifestyle.VERY_ACTIVE)
    assert high.floor_kcal == floor
    assert high.floor_applied is False
    assert "floor" not in high.explanation.lower()
    low = _targets(sex=sex, weight_kg=35, height_cm=120, age_years=90, goal=Goal.CUTTING)
    assert low.floor_kcal == floor
    assert low.floor_applied is True
    assert low.kcal == floor


@given(
    sex=st.sampled_from(list(Sex)),
    weight=ranges["weight_kg"],
    height=ranges["height_cm"],
    age=ranges["age_years"],
    bf=st.one_of(st.none(), ranges["body_fat_pct"]),
    lifestyle=st.sampled_from(list(Lifestyle)),
    goal=st.sampled_from(list(Goal)),
    exercise=ranges["exercise"],
)
@settings(max_examples=300)
def test_kcal_never_below_floor_and_macros_sum(
    sex: Sex,
    weight: float,
    height: float,
    age: int,
    bf: float | None,
    lifestyle: Lifestyle,
    goal: Goal,
    exercise: float,
) -> None:
    r = _targets(
        sex=sex,
        weight_kg=weight,
        height_cm=height,
        age_years=age,
        body_fat_pct=bf,
        lifestyle=lifestyle,
        goal=goal,
        planned_exercise_kcal_per_week=exercise,
    )
    # F3.6: never below the floor.
    assert r.kcal >= c.CALORIE_FLOOR_KCAL[sex] == r.floor_kcal
    # F3.4 AC: macro kcal sum within ±1 % of kcal, or carbs clamped and explained.
    macro_kcal = 4 * r.protein_g + 4 * r.carbs_g + 9 * r.fat_g
    if r.carbs_clamped:
        assert r.carbs_g == 0
        assert "carbs clamped at 0" in r.explanation
    else:
        assert abs(macro_kcal - r.kcal) <= 0.01 * r.kcal
    # D47 balance from the reported fields.
    assert r.target_balance_kcal == r.kcal - (r.baseline_kcal + r.planned_exercise_kcal_per_day)
    assert all(math.isfinite(v) for v in (r.protein_g, r.carbs_g, r.fat_g))
    assert min(r.protein_g, r.carbs_g, r.fat_g) >= 0


# ─────────────────────────────── F3.5 macros ───────────────────────────────


def test_fat_uses_25_percent_of_kcal_when_higher() -> None:
    # Male 80/180/30 sedentary maintenance: kcal 2136; 25 % → 59.3 g > 0.6 × 80 = 48 g.
    r = _targets()
    assert r.kcal == 2136
    assert r.fat_g == 59.3
    assert r.protein_g == 128.0
    assert r.carbs_g == round_grams((2136 - 4 * 128.0 - 9 * 59.3) / 4)


def test_fat_uses_minimum_g_per_kg_when_higher() -> None:
    # TargetsAna: 25 % of 1515 = 42.1 g < 0.6 × 72.5 = 43.5 g.
    r = _targets(
        sex=Sex.FEMALE,
        weight_kg=72.5,
        body_fat_pct=35.2,
        lifestyle=Lifestyle.LIGHTLY_ACTIVE,
        goal=Goal.CUTTING,
        planned_exercise_kcal_per_week=658,
    )
    assert r.fat_g == 43.5


def test_carbs_clamped_case() -> None:
    # BMR 3367.5 → 4041 → × 0.8 = 3232.8 → 3233 kcal; protein 550 g (2200 kcal) +
    # fat max(89.8, 150) = 150 g (1350 kcal) = 3550 kcal > 3233.
    r = _targets(
        sex=Sex.MALE,
        weight_kg=250,
        height_cm=170,
        age_years=40,
        lifestyle=Lifestyle.SEDENTARY,
        goal=Goal.CUTTING,
    )
    assert r.kcal == 3233
    assert r.carbs_clamped is True
    assert r.carbs_g == 0
    assert r.protein_g == 550
    assert r.fat_g == 150
    assert "carbs clamped at 0" in r.explanation


def test_energy_constants() -> None:
    assert (c.KCAL_PER_G_PROTEIN, c.KCAL_PER_G_CARBS, c.KCAL_PER_G_FAT) == (4, 4, 9)
    assert c.FAT_SHARE_OF_KCAL == 0.25
    assert c.FAT_MIN_G_PER_KG == 0.6


# ─────────────────────────────── F3.5 explanation ───────────────────────────────


def test_explanation_katch_mcardle_names_formula_and_numbers() -> None:
    r = _targets(
        sex=Sex.FEMALE,
        weight_kg=72.5,
        height_cm=165,
        age_years=35,
        body_fat_pct=35.2,
        lifestyle=Lifestyle.LIGHTLY_ACTIVE,
        goal=Goal.CUTTING,
        planned_exercise_kcal_per_week=658,
    )
    for fragment in (
        "Katch-McArdle",
        "LBM 46.98 kg",
        "35.2 %",
        "72.5 kg",
        "1385 kcal",
        "1385 × 1.30 (lightly active) = 1800 kcal",
        "94 planned exercise",
        "658 kcal/week",
        "− 20 %",
        "1515 kcal",
        "2.2 g/kg",
        "159.5 g",
        "25 % of 1515 kcal",
        "0.6 g/kg",
        "43.5 g",
        "121.4 g",
        "-379",
    ):
        assert fragment in r.explanation, fragment


def test_explanation_mifflin_names_formula_and_inputs() -> None:
    r = _targets(sex=Sex.UNSPECIFIED, weight_kg=70, height_cm=170, age_years=40)
    for fragment in (
        "Mifflin-St Jeor",
        "10 × 70 kg",
        "6.25 × 170 cm",
        "5 × 40 y",
        "− 78",
        "prefer not to say",
        "1485 kcal",
        "1.20 (sedentary)",
        "+ 0 %",
        "1.6 g/kg",
    ):
        assert fragment in r.explanation, fragment


# ─────────────────────────────── input validation ───────────────────────────────


@pytest.mark.parametrize(
    "overrides",
    [
        {"weight_kg": 0},
        {"height_cm": -1},
        {"age_years": math.nan},
        {"body_fat_pct": 100},
        {"body_fat_pct": -1},
        {"planned_exercise_kcal_per_week": -1},
        {"planned_exercise_kcal_per_week": math.inf},
    ],
)
def test_invalid_inputs_raise_value_error(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _targets(**overrides)


def test_unknown_enum_values_raise_value_error() -> None:
    with pytest.raises(ValueError):
        _targets(goal="bulking")


# ─────────────────────────────── monotonicity ───────────────────────────────


@given(
    sex=st.sampled_from(list(Sex)),
    w1=ranges["weight_kg"],
    w2=ranges["weight_kg"],
    height=ranges["height_cm"],
    age=ranges["age_years"],
    bf=st.one_of(st.none(), ranges["body_fat_pct"]),
)
def test_more_weight_never_lowers_bmr(
    sex: Sex, w1: float, w2: float, height: float, age: int, bf: float | None
) -> None:
    lo, hi = sorted((w1, w2))
    bmr_lo = _targets(sex=sex, weight_kg=lo, height_cm=height, age_years=age, body_fat_pct=bf)
    bmr_hi = _targets(sex=sex, weight_kg=hi, height_cm=height, age_years=age, body_fat_pct=bf)
    assert bmr_hi.bmr_kcal >= bmr_lo.bmr_kcal
    assert compute_bmr(sex, hi, height, age, bf).bmr >= compute_bmr(sex, lo, height, age, bf).bmr


@given(
    sex=st.sampled_from(list(Sex)),
    weight=ranges["weight_kg"],
    height=ranges["height_cm"],
    age=ranges["age_years"],
    bf=st.one_of(st.none(), ranges["body_fat_pct"]),
    pair=st.lists(st.sampled_from(list(Lifestyle)), min_size=2, max_size=2),
)
def test_higher_lifestyle_factor_never_lowers_baseline(
    sex: Sex, weight: float, height: float, age: int, bf: float | None, pair: list[Lifestyle]
) -> None:
    lo, hi = sorted(pair, key=lambda ls: c.LIFESTYLE_FACTORS[ls])
    common = {"sex": sex, "weight_kg": weight, "height_cm": height, "age_years": age}
    base_lo = _targets(**common, body_fat_pct=bf, lifestyle=lo).baseline_kcal
    base_hi = _targets(**common, body_fat_pct=bf, lifestyle=hi).baseline_kcal
    assert base_hi >= base_lo


@given(
    sex=st.sampled_from(list(Sex)),
    weight=ranges["weight_kg"],
    height=ranges["height_cm"],
    age=ranges["age_years"],
    bf=st.one_of(st.none(), ranges["body_fat_pct"]),
    lifestyle=st.sampled_from(list(Lifestyle)),
    goal=st.sampled_from(list(Goal)),
    e1=ranges["exercise"],
    e2=ranges["exercise"],
)
def test_more_planned_exercise_never_lowers_kcal(
    sex: Sex,
    weight: float,
    height: float,
    age: int,
    bf: float | None,
    lifestyle: Lifestyle,
    goal: Goal,
    e1: float,
    e2: float,
) -> None:
    lo, hi = sorted((e1, e2))
    common = {
        "sex": sex,
        "weight_kg": weight,
        "height_cm": height,
        "age_years": age,
        "body_fat_pct": bf,
        "lifestyle": lifestyle,
        "goal": goal,
    }
    assert (
        _targets(**common, planned_exercise_kcal_per_week=hi).kcal
        >= _targets(**common, planned_exercise_kcal_per_week=lo).kcal
    )


# ─────────────────────────────── helpers ───────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"), [(1484.5, 1485), (1320.25, 1320), (-378.5, -379), (0.49, 0)]
)
def test_round_kcal_is_half_up(value: float, expected: int) -> None:
    assert round_kcal(value) == expected


def test_round_grams_is_half_up() -> None:
    assert round_grams(121.375) == 121.4
    assert round_grams(0.05) == 0.1
