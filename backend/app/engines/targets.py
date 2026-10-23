"""F3 targets engine: BMR, baseline, Navy body fat, daily calories, macros and calorie floor.

Pure functions (ADR 0004, CLAUDE.md rule 3): plain inputs in, a result with an `explanation` out.
No database, HTTP, clock, flags or environment access; every coefficient lives in
`app.engines.constants` (F3 block). The service layer (#25) gathers the inputs (latest body
metric, profile, planned weekly exercise kcal from the F13.2 engine) and stores the result.

Rounding: the chain BMR → baseline → target is computed at full precision and each kcal output
is rounded half-up to an integer (`Kcal`). Macros are derived from the rounded target `kcal` and
rounded half-up to 0.1 g; carbs use the rounded protein and fat so the macro kcal sum matches
`kcal` (F3.4 AC). `target_balance_kcal` (D47) is computed from the reported integer fields so the
numbers the user sees add up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from app.engines import constants as c


class Sex(StrEnum):
    """Sex for calculations; `unspecified` = "prefer not to say" (midpoint constants)."""

    MALE = "male"
    FEMALE = "female"
    UNSPECIFIED = "unspecified"


class Lifestyle(StrEnum):
    """Non-exercise activity level (F3.2)."""

    SEDENTARY = "sedentary"
    LIGHTLY_ACTIVE = "lightly_active"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


class Goal(StrEnum):
    """Training/nutrition goal (F3.4)."""

    RECOMPOSITION = "recomposition"
    MUSCLE_GAIN = "muscle_gain"
    CUTTING = "cutting"
    MAINTENANCE = "maintenance"
    WELLNESS = "wellness"


class BmrFormula(StrEnum):
    KATCH_MCARDLE = "katch_mcardle"
    MIFFLIN_ST_JEOR = "mifflin_st_jeor"


_LIFESTYLE_LABELS = {
    Lifestyle.SEDENTARY: "sedentary",
    Lifestyle.LIGHTLY_ACTIVE: "lightly active",
    Lifestyle.ACTIVE: "active",
    Lifestyle.VERY_ACTIVE: "very active",
}
_SEX_LABELS = {Sex.MALE: "male", Sex.FEMALE: "female", Sex.UNSPECIFIED: "prefer not to say"}


@dataclass(frozen=True)
class BmrResult:
    formula: BmrFormula
    bmr: float
    """Unrounded BMR (kcal/day)."""
    explanation: str


@dataclass(frozen=True)
class NavyResult:
    body_fat_pct: float
    """Unrounded estimate (%). Range checks are the caller's decision (#25)."""
    explanation: str


@dataclass(frozen=True)
class TargetsResult:
    """Computed fields of the contract's `Targets` schema (openapi.yaml)."""

    bmr_formula: BmrFormula
    bmr_kcal: int
    lifestyle_factor: float
    baseline_kcal: int
    planned_exercise_kcal_per_day: int
    goal_adjustment_pct: float
    kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float
    target_balance_kcal: int
    floor_applied: bool
    floor_kcal: int
    carbs_clamped: bool
    weight_used_kg: float
    body_fat_pct_used: float | None
    explanation: str
    inputs: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────── helpers ───────────────────────────────


def round_kcal(value: float) -> int:
    """Round half-up to a whole kcal (Python's round() is half-to-even)."""
    return int(Decimal(repr(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_grams(value: float) -> float:
    """Round half-up to 0.1 g."""
    return float(Decimal(repr(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _num(value: float) -> str:
    """Short human form of a number: 72.5, 180, 35.2."""
    return f"{value:g}" if abs(value) < 1e6 else f"{value:.0f}"


def _signed_pct(fraction: float) -> str:
    pct = abs(fraction) * 100
    sign = "−" if fraction < 0 else "+"
    return f"{sign} {pct:g} %"


def _require_finite_positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number (got {value!r})")


# ─────────────────────────────── F3.1 BMR ───────────────────────────────


def katch_mcardle_bmr(weight_kg: float, body_fat_pct: float) -> BmrResult:
    """F3.1 Katch-McArdle: BMR = 370 + 21.6 × LBM, LBM = weight × (1 − bf%)."""
    _require_finite_positive("weight_kg", weight_kg)
    if not math.isfinite(body_fat_pct) or not 0 <= body_fat_pct < 100:
        raise ValueError(f"body_fat_pct must be in [0, 100) (got {body_fat_pct!r})")
    lbm = weight_kg * (1 - body_fat_pct / 100)
    bmr = c.KATCH_MCARDLE_INTERCEPT_KCAL + c.KATCH_MCARDLE_KCAL_PER_KG_LBM * lbm
    explanation = (
        f"BMR (Katch-McArdle) = {_num(c.KATCH_MCARDLE_INTERCEPT_KCAL)} + "
        f"{_num(c.KATCH_MCARDLE_KCAL_PER_KG_LBM)} × LBM {lbm:.2f} kg = {round_kcal(bmr)} kcal "
        f"(LBM = {_num(weight_kg)} kg × (1 − {_num(body_fat_pct)} % body fat))."
    )
    return BmrResult(BmrFormula.KATCH_MCARDLE, bmr, explanation)


def mifflin_st_jeor_bmr(
    sex: Sex, weight_kg: float, height_cm: float, age_years: float
) -> BmrResult:
    """F3.1 Mifflin-St Jeor: BMR = 10·kg + 6.25·cm − 5·age + s."""
    _require_finite_positive("weight_kg", weight_kg)
    _require_finite_positive("height_cm", height_cm)
    _require_finite_positive("age_years", age_years)
    s = c.MIFFLIN_SEX_CONSTANT_KCAL[Sex(sex)]
    bmr = (
        c.MIFFLIN_KCAL_PER_KG * weight_kg
        + c.MIFFLIN_KCAL_PER_CM * height_cm
        + c.MIFFLIN_KCAL_PER_YEAR * age_years
        + s
    )
    s_text = f"+ {_num(s)}" if s >= 0 else f"− {_num(-s)}"
    explanation = (
        f"BMR (Mifflin-St Jeor) = {_num(c.MIFFLIN_KCAL_PER_KG)} × {_num(weight_kg)} kg + "
        f"{_num(c.MIFFLIN_KCAL_PER_CM)} × {_num(height_cm)} cm − "
        f"{_num(-c.MIFFLIN_KCAL_PER_YEAR)} × {_num(age_years)} y {s_text} "
        f"({_SEX_LABELS[Sex(sex)]}) = {round_kcal(bmr)} kcal."
    )
    return BmrResult(BmrFormula.MIFFLIN_ST_JEOR, bmr, explanation)


def compute_bmr(
    sex: Sex,
    weight_kg: float,
    height_cm: float,
    age_years: float,
    body_fat_pct: float | None,
) -> BmrResult:
    """F3.2: Katch-McArdle if and only if a body-fat value exists, else Mifflin-St Jeor."""
    if body_fat_pct is not None:
        return katch_mcardle_bmr(weight_kg, body_fat_pct)
    return mifflin_st_jeor_bmr(sex, weight_kg, height_cm, age_years)


# ─────────────────────────────── F3.3 Navy ───────────────────────────────


def navy_body_fat(
    sex: Sex,
    height_cm: float,
    neck_cm: float,
    waist_cm: float,
    hip_cm: float | None = None,
) -> NavyResult:
    """F3.3 US Navy tape estimate (cm, log10). Hip is required for female / unspecified.

    Raises ValueError when the log argument is not positive (male waist ≤ neck; female /
    unspecified waist + hip ≤ neck) or the result would not be a finite number.
    """
    sex = Sex(sex)
    _require_finite_positive("height_cm", height_cm)
    _require_finite_positive("neck_cm", neck_cm)
    _require_finite_positive("waist_cm", waist_cm)
    if sex is Sex.MALE:
        a, b, k = c.NAVY_MALE_COEFFICIENTS
        x = waist_cm - neck_cm
        if x <= 0:
            raise ValueError("Navy estimate needs a waist larger than the neck measurement.")
        x_text = f"waist {_num(waist_cm)} − neck {_num(neck_cm)}"
    else:
        if hip_cm is None:
            raise ValueError("Navy estimate for female / unspecified needs a hip measurement.")
        _require_finite_positive("hip_cm", hip_cm)
        a, b, k = c.NAVY_FEMALE_COEFFICIENTS
        x = waist_cm + hip_cm - neck_cm
        if x <= 0:
            raise ValueError("Navy estimate needs waist + hip larger than the neck measurement.")
        x_text = f"waist {_num(waist_cm)} + hip {_num(hip_cm)} − neck {_num(neck_cm)}"
    denominator = a - b * math.log10(x) + k * math.log10(height_cm)
    if denominator <= 0:
        raise ValueError("Navy estimate is undefined for these measurements.")
    bf = c.NAVY_NUMERATOR / denominator - c.NAVY_OFFSET
    if not math.isfinite(bf):  # pragma: no cover - defensive; denominator > 0 keeps it finite
        raise ValueError("Navy estimate is undefined for these measurements.")
    explanation = (
        f"Body fat (US Navy, {_SEX_LABELS[sex]}) = {_num(c.NAVY_NUMERATOR)} / ({a} − {b} × "
        f"log10({x_text} = {_num(x)} cm) + {k} × log10(height {_num(height_cm)} cm)) − "
        f"{_num(c.NAVY_OFFSET)} = {bf:.1f} %."
    )
    return NavyResult(bf, explanation)


# ─────────────────────────────── F3.2 to F3.6 targets ───────────────────────────────


def compute_targets(
    *,
    sex: Sex,
    weight_kg: float,
    height_cm: float,
    age_years: float,
    body_fat_pct: float | None,
    lifestyle: Lifestyle,
    goal: Goal,
    planned_exercise_kcal_per_week: float,
) -> TargetsResult:
    """Daily calorie and macro targets (F3.1 to F3.6) with a human-readable explanation."""
    sex, lifestyle, goal = Sex(sex), Lifestyle(lifestyle), Goal(goal)
    if not math.isfinite(planned_exercise_kcal_per_week) or planned_exercise_kcal_per_week < 0:
        raise ValueError(
            "planned_exercise_kcal_per_week must be a non-negative finite number "
            f"(got {planned_exercise_kcal_per_week!r})"
        )

    # F3.1 BMR
    bmr = compute_bmr(sex, weight_kg, height_cm, age_years, body_fat_pct)

    # F3.2 baseline
    factor = c.LIFESTYLE_FACTORS[lifestyle]
    baseline = bmr.bmr * factor

    # F3.4 target
    exercise_per_day = planned_exercise_kcal_per_week / c.DAYS_PER_WEEK
    adjustment = c.GOAL_ADJUSTMENTS[goal]
    computed_kcal = round_kcal((baseline + exercise_per_day) * (1 + adjustment))

    # F3.6 floor
    floor_kcal = c.CALORIE_FLOOR_KCAL[sex]
    floor_applied = computed_kcal < floor_kcal
    kcal = floor_kcal if floor_applied else computed_kcal

    # F3.5 macros (from the final kcal)
    protein_per_kg = c.PROTEIN_G_PER_KG[goal]
    protein_g = round_grams(protein_per_kg * weight_kg)
    fat_by_share = c.FAT_SHARE_OF_KCAL * kcal / c.KCAL_PER_G_FAT
    fat_by_weight = c.FAT_MIN_G_PER_KG * weight_kg
    fat_g = round_grams(max(fat_by_share, fat_by_weight))
    remaining = kcal - c.KCAL_PER_G_PROTEIN * protein_g - c.KCAL_PER_G_FAT * fat_g
    carbs_clamped = remaining < 0
    carbs_g = 0.0 if carbs_clamped else round_grams(remaining / c.KCAL_PER_G_CARBS)

    bmr_kcal = round_kcal(bmr.bmr)
    baseline_kcal = round_kcal(baseline)
    exercise_kcal_per_day = round_kcal(exercise_per_day)
    # D47: the goal's target daily balance, from the reported integer fields.
    target_balance_kcal = kcal - (baseline_kcal + exercise_kcal_per_day)

    parts = [
        bmr.explanation,
        f"Baseline = {bmr_kcal} × {factor:.2f} ({_LIFESTYLE_LABELS[lifestyle]}) = "
        f"{baseline_kcal} kcal.",
        f"Target = ({baseline_kcal} + {exercise_kcal_per_day} planned exercise per day, "
        f"{_num(planned_exercise_kcal_per_week)} kcal/week ÷ {c.DAYS_PER_WEEK}) × "
        f"(1 {_signed_pct(adjustment)}) = {computed_kcal} kcal.",
    ]
    if floor_applied:
        parts.append(
            f"Calorie floor applied: {computed_kcal} kcal is below the {floor_kcal} kcal minimum "
            f"({_SEX_LABELS[sex]}), so the target is raised to {floor_kcal} kcal."
        )
    fat_rule = (
        f"fat max(25 % of {kcal} kcal = {fat_by_share:.1f} g, "
        f"{_num(c.FAT_MIN_G_PER_KG)} g/kg × {_num(weight_kg)} kg = {fat_by_weight:.1f} g) "
        f"= {_num(fat_g)} g"
    )
    protein_text = (
        f"Protein {_num(protein_per_kg)} g/kg × {_num(weight_kg)} kg = {_num(protein_g)} g"
    )
    if carbs_clamped:
        carbs_text = (
            f"carbs clamped at 0 g because protein and fat already exceed {kcal} kcal "
            f"(macros total {round_kcal(kcal - remaining)} kcal)"
        )
    else:
        carbs_text = f"carbs = rest = {_num(carbs_g)} g"
    parts.append(f"{protein_text}; {fat_rule}; {carbs_text}.")
    parts.append(
        f"Target balance = {kcal} − ({baseline_kcal} + {exercise_kcal_per_day}) = "
        f"{target_balance_kcal} kcal/day. All values are estimates."
    )

    inputs: dict[str, Any] = {
        "sex": sex.value,
        "weight_kg": weight_kg,
        "height_cm": height_cm,
        "age_years": age_years,
        "body_fat_pct": body_fat_pct,
        "lifestyle": lifestyle.value,
        "goal": goal.value,
        "planned_exercise_kcal_per_week": planned_exercise_kcal_per_week,
    }

    return TargetsResult(
        bmr_formula=bmr.formula,
        bmr_kcal=bmr_kcal,
        lifestyle_factor=factor,
        baseline_kcal=baseline_kcal,
        planned_exercise_kcal_per_day=exercise_kcal_per_day,
        goal_adjustment_pct=round(adjustment * 100, 2),
        kcal=kcal,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        target_balance_kcal=target_balance_kcal,
        floor_applied=floor_applied,
        floor_kcal=floor_kcal,
        carbs_clamped=carbs_clamped,
        weight_used_kg=weight_kg,
        body_fat_pct_used=body_fat_pct,
        explanation=" ".join(parts),
        inputs=inputs,
    )
