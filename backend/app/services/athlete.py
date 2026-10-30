"""Onboarding, profile and targets (spec F2, F3, F7; D41, D43, D46, D55).

`onboard` is one transaction: profile, first `BodyMetric`, `Targets` and plan version 1 (training
and meal plan) are committed together or not at all. The pure engines (targets, training plan,
meal plan, exercise kcal) do the maths; this module gathers their inputs and stores their results.

Nothing here logs and no span carries values: profile data, weights and measurements are health
data (spec section 6.5). Only the `engine.targets` span marks the engine call.
"""

import dataclasses
import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.engines import exercise_kcal as kcal_engine
from app.engines import targets as targets_engine
from app.engines.meal_plan import GeneratedMealPlan
from app.engines.training_plan import CatalogExercise, GeneratedPlan, PlanRequest, generate_plan
from app.errors import ProblemError
from app.models import AthleteProfile, BodyMetric, Exercise, Plan, Targets, TrainingDay, User
from app.schemas import athlete as out
from app.schemas.athlete import AthleteProfileInput, OnboardingBodyMetric, OnboardingRequest
from app.schemas.problem import FieldError
from app.services import meal_plans
from app.services.clock import age_on, local_today
from app.services.plans import (
    NewMealDay,
    NewPlannedExercise,
    NewPlannedMeal,
    NewTrainingDay,
    create_plan_version,
    plan_view,
)
from app.telemetry import Telemetry

BODY_FAT_MIN_PCT = 3.0  # F2.3 / F2.6: plausible range, also applied to Navy results (D55)
BODY_FAT_MAX_PCT = 60.0

# Profile fields whose change recomputes targets (D46, openapi `updateAthleteProfile`).
TARGET_RELEVANT_FIELDS = (
    "sex",
    "height_cm",
    "lifestyle",
    "goal",
    "days_per_week",
    "session_minutes",
)

# (exercise type, MET, sets, rest seconds, target seconds) per planned exercise.
type _KcalExercise = tuple[str, float, int, int, int | None]


# ───────────── helpers ─────────────


def _round(value: float, places: int) -> float:
    """Round half up (not banker's rounding) to `places` decimals, for the column scale."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _round_opt(value: float | None, places: int) -> float | None:
    return None if value is None else _round(value, places)


def _invalid(field: str, code: str, message: str) -> FieldError:
    return FieldError(field=field, code=code, message=message)


def require_athlete(user: User) -> None:
    """Only athletes have a profile; a coach calling an athlete-only operation gets 403."""
    if user.role != "athlete":
        raise ProblemError(403, "wrong_role", "Only athletes can do this.")


def _check_avoided_exercises(
    session: Session, user_id: uuid.UUID, ids: Sequence[uuid.UUID], prefix: str
) -> None:
    if not ids:
        return
    known = set(
        session.scalars(
            select(Exercise.id).where(
                Exercise.id.in_(ids),
                (Exercise.owner_id.is_(None)) | (Exercise.owner_id == user_id),
            )
        )
    )
    if known != set(ids):
        raise ProblemError(
            422,
            "validation_error",
            errors=[
                _invalid(
                    f"{prefix}avoided_exercise_ids",
                    "invalid_choice",
                    "Pick exercises from the catalog.",
                )
            ],
        )


def _check_body_metric(profile: AthleteProfileInput, metric: OnboardingBodyMetric) -> None:
    """Cross-field rules of the wizard's body step (F2, F3.3)."""
    errors: list[FieldError] = []
    prefix = "body_metric."
    if metric.body_fat_method == "entered":
        if metric.body_fat_pct is None:
            errors.append(
                _invalid(prefix + "body_fat_pct", "required", "Enter your body fat percentage.")
            )
    elif metric.body_fat_pct is not None:
        errors.append(
            _invalid(
                prefix + "body_fat_pct",
                "not_allowed",
                "Send body_fat_pct only with body_fat_method 'entered'.",
            )
        )
    if metric.body_fat_method == "navy":
        needed = ["neck_cm", "waist_cm"] + (["hip_cm"] if profile.sex != "male" else [])
        errors.extend(
            _invalid(prefix + name, "required", "This measurement is needed for the Navy method.")
            for name in needed
            if getattr(metric, name) is None
        )
    if errors:
        raise ProblemError(422, "validation_error", errors=errors)


def _body_fat_from_metric(
    profile: AthleteProfileInput, metric: OnboardingBodyMetric
) -> tuple[float | None, str | None, str | None, str | None]:
    """(body fat %, method, Navy explanation, note for the targets explanation).

    A Navy result outside 3-60 % (or one the formula cannot compute) is ignored: no body fat is
    stored, the targets use Mifflin-St Jeor and the note says so (F2.6, D55).
    """
    if metric.body_fat_method == "entered":
        assert metric.body_fat_pct is not None  # noqa: S101 - checked by _check_body_metric
        return _round(metric.body_fat_pct, 1), "entered", None, None
    if metric.body_fat_method != "navy":
        return None, None, None, None
    assert metric.neck_cm is not None and metric.waist_cm is not None  # noqa: S101
    try:
        navy = targets_engine.navy_body_fat(
            targets_engine.Sex(profile.sex),
            profile.height_cm,
            metric.neck_cm,
            metric.waist_cm,
            metric.hip_cm,
        )
    except ValueError:
        return (
            None,
            None,
            None,
            "The Navy body-fat estimate could not be computed from these measurements and was "
            "ignored; BMR uses Mifflin-St Jeor.",
        )
    value = _round(navy.body_fat_pct, 1)
    if not BODY_FAT_MIN_PCT <= value <= BODY_FAT_MAX_PCT:
        return (
            None,
            None,
            None,
            f"The Navy body-fat estimate ({value:g} %) was out of range "
            f"({BODY_FAT_MIN_PCT:g}-{BODY_FAT_MAX_PCT:g} %) and ignored; BMR uses "
            "Mifflin-St Jeor.",
        )
    return value, "navy", navy.explanation, None


def _catalog(session: Session) -> list[CatalogExercise]:
    rows = session.scalars(select(Exercise).where(Exercise.owner_id.is_(None)))
    return [
        CatalogExercise(
            id=str(e.id),
            name=e.name,
            muscle_group=e.muscle_group,
            equipment=e.equipment,
            type=e.type,
            met=float(e.met),
            increment_kg=float(e.increment_kg),
        )
        for e in rows
    ]


def _weekly_kcal(
    days: Sequence[tuple[str, Sequence[_KcalExercise]]], weight_kg: float
) -> kcal_engine.PlannedWeeklyKcal:
    """F13.2 over `(weekday, exercises)` days at `weight_kg`."""
    return kcal_engine.planned_weekly_kcal(
        [
            kcal_engine.PlannedDay(
                label=weekday,
                exercises=[
                    kcal_engine.PlannedExercise(
                        exercise_type=etype,  # type: ignore[arg-type]
                        met=met,
                        sets=sets,
                        rest_seconds=rest,
                        target_seconds=target,
                    )
                    for etype, met, sets, rest, target in exercises
                ],
            )
            for weekday, exercises in days
        ],
        weight_kg,
    )


def generate_training(
    session: Session, profile: AthleteProfileInput | AthleteProfile, weight_kg: float
) -> tuple[GeneratedPlan, kcal_engine.PlannedWeeklyKcal, list[NewTrainingDay]]:
    """Run the F5 engine for `profile` and price the days with F13.2 at `weight_kg`.

    Shared by onboarding and "regenerate" (F8.2): both store the days as a plan version."""
    catalog = _catalog(session)
    by_id = {c.id: c for c in catalog}
    generated = generate_plan(
        PlanRequest(
            experience=profile.experience,
            goal=profile.goal,
            days_per_week=profile.days_per_week,
            preferred_days=list(profile.preferred_days),
            session_minutes=profile.session_minutes,
            equipment=profile.equipment,
            avoided_exercise_ids=[str(i) for i in profile.avoided_exercise_ids],
        ),
        catalog,
    )
    weekly = _weekly_kcal(
        [
            (
                day.weekday,
                [
                    (
                        by_id[e.exercise_id].type,
                        by_id[e.exercise_id].met,
                        e.sets,
                        e.rest_seconds,
                        e.target_seconds,
                    )
                    for e in day.exercises
                ],
            )
            for day in generated.days
        ],
        weight_kg,
    )
    days = [
        NewTrainingDay(
            weekday=day.weekday,
            name=day.name,
            planned_kcal=day_kcal.kcal,
            exercises=[
                NewPlannedExercise(
                    exercise_id=uuid.UUID(e.exercise_id),
                    sets=e.sets,
                    rest_seconds=e.rest_seconds,
                    rule=e.rule,
                    increment_kg=e.increment_kg,
                    reps_min=e.reps_min,
                    reps_max=e.reps_max,
                    target_weight_kg=e.target_weight_kg,
                    target_seconds=e.target_seconds,
                    deload_enabled=e.deload_enabled,
                    planned_kcal=part.kcal,
                )
                for e, part in zip(day.exercises, day_kcal.parts, strict=True)
            ],
        )
        for day, day_kcal in zip(generated.days, weekly.days, strict=True)
    ]
    return generated, weekly, days


def new_meal_days(generated: GeneratedMealPlan) -> list[NewMealDay]:
    return [
        NewMealDay(
            weekday=day.weekday,
            warning=day.warning,
            meals=[
                NewPlannedMeal(m.slot, uuid.UUID(m.meal_id), m.portion_factor) for m in day.meals
            ],
        )
        for day in generated.days
    ]


def _compute_targets(
    telemetry: Telemetry,
    *,
    sex: str,
    height_cm: float,
    lifestyle: str,
    goal: str,
    age_years: int,
    weight_kg: float,
    body_fat_pct: float | None,
    planned_weekly_kcal_exact: float,
    note: str | None,
) -> targets_engine.TargetsResult:
    """The `engine.targets` span wraps only the engine call and carries no values."""
    with telemetry.engine_span("targets"):
        result = targets_engine.compute_targets(
            sex=targets_engine.Sex(sex),
            weight_kg=weight_kg,
            height_cm=float(height_cm),
            age_years=age_years,
            body_fat_pct=body_fat_pct,
            lifestyle=targets_engine.Lifestyle(lifestyle),
            goal=targets_engine.Goal(goal),
            planned_exercise_kcal_per_week=planned_weekly_kcal_exact,
        )
    if note:
        result = dataclasses.replace(result, explanation=f"{note} {result.explanation}")
    return result


def _store_targets(
    session: Session,
    user_id: uuid.UUID,
    valid_from: dt.date,
    result: targets_engine.TargetsResult,
    now: dt.datetime,
) -> Targets:
    """Add the row for `valid_from`, or replace the one written earlier the same local day."""
    row = session.scalar(
        select(Targets).where(Targets.user_id == user_id, Targets.valid_from == valid_from)
    )
    if row is None:
        row = Targets(user_id=user_id, valid_from=valid_from)
        session.add(row)
    row.bmr_formula = result.bmr_formula.value
    row.bmr_kcal = result.bmr_kcal
    row.lifestyle_factor = result.lifestyle_factor
    row.baseline_kcal = result.baseline_kcal
    row.planned_exercise_kcal_per_day = result.planned_exercise_kcal_per_day
    row.goal_adjustment_pct = result.goal_adjustment_pct
    row.kcal = result.kcal
    row.protein_g = result.protein_g
    row.carbs_g = result.carbs_g
    row.fat_g = result.fat_g
    row.target_balance_kcal = result.target_balance_kcal
    row.floor_applied = result.floor_applied
    row.floor_kcal = result.floor_kcal
    row.carbs_clamped = result.carbs_clamped
    row.weight_used_kg = result.weight_used_kg
    row.body_fat_pct_used = result.body_fat_pct_used
    row.explanation = result.explanation
    row.inputs = result.inputs
    row.created_at = now
    session.flush()
    return row


def store_kcal(
    session: Session, user_id: uuid.UUID, valid_from: dt.date, kcal: int, now: dt.datetime
) -> Targets:
    """Targets from `valid_from` with a new daily kcal (adaptive calories, F14): protein and fat
    stay, carbs take the difference (never below 0), the balance follows the kcal."""
    current = targets_on(session, user_id, valid_from)
    if current is None:
        raise _not_onboarded()
    remaining = kcal - 4 * float(current.protein_g) - 9 * float(current.fat_g)
    carbs_clamped = remaining < 0
    row = session.scalar(
        select(Targets).where(Targets.user_id == user_id, Targets.valid_from == valid_from)
    )
    if row is None:
        row = Targets(user_id=user_id, valid_from=valid_from)
        session.add(row)
    fields = {
        col.key: getattr(current, col.key)
        for col in Targets.__table__.columns
        if col.key not in ("id", "user_id", "valid_from")
    }
    for key, value in fields.items():
        setattr(row, key, value)
    row.kcal = kcal
    row.carbs_g = 0.0 if carbs_clamped else round(remaining / 4, 1)
    row.carbs_clamped = carbs_clamped
    row.target_balance_kcal = kcal - (row.baseline_kcal + row.planned_exercise_kcal_per_day)
    row.floor_applied = kcal <= row.floor_kcal
    row.explanation = (
        f"{current.explanation} Adjusted to {kcal} kcal by an accepted adaptive calorie "
        "suggestion; protein and fat are unchanged and carbs take the difference."
    )
    row.created_at = now
    session.flush()
    return row


# ───────────── views ─────────────


def _profile_view(row: AthleteProfile) -> out.AthleteProfile:
    return out.AthleteProfile.model_validate(
        {
            "athlete_id": row.user_id,
            "sex": row.sex,
            "height_cm": row.height_cm,
            "lifestyle": row.lifestyle,
            "goal": row.goal,
            "experience": row.experience,
            "days_per_week": row.days_per_week,
            "preferred_days": row.preferred_days,
            "session_minutes": row.session_minutes,
            "equipment": row.equipment,
            "avoided_exercise_ids": row.avoided_exercise_ids,
            "diet": row.diet,
            "allergies": row.allergies,
            "meals_per_day": row.meals_per_day,
            "updated_at": row.updated_at.astimezone(dt.UTC),
        }
    )


def _metric_view(row: BodyMetric) -> out.BodyMetric:
    return out.BodyMetric.model_validate(
        {
            "id": row.id,
            "date": row.date,
            "weight_kg": row.weight_kg,
            "body_fat_pct": row.body_fat_pct,
            "body_fat_method": row.bf_method,
            "body_fat_explanation": row.body_fat_explanation,
            "neck_cm": row.neck_cm,
            "waist_cm": row.waist_cm,
            "hip_cm": row.hip_cm,
            "created_at": row.created_at.astimezone(dt.UTC),
        }
    )


def _targets_view(row: Targets) -> out.Targets:
    return out.Targets.model_validate(
        {
            "id": row.id,
            "athlete_id": row.user_id,
            "valid_from": row.valid_from,
            "bmr_formula": row.bmr_formula,
            "bmr_kcal": row.bmr_kcal,
            "lifestyle_factor": row.lifestyle_factor,
            "baseline_kcal": row.baseline_kcal,
            "planned_exercise_kcal_per_day": row.planned_exercise_kcal_per_day,
            "goal_adjustment_pct": row.goal_adjustment_pct,
            "kcal": row.kcal,
            "protein_g": row.protein_g,
            "carbs_g": row.carbs_g,
            "fat_g": row.fat_g,
            "target_balance_kcal": row.target_balance_kcal,
            "floor_applied": row.floor_applied,
            "floor_kcal": row.floor_kcal,
            "carbs_clamped": row.carbs_clamped,
            "weight_used_kg": row.weight_used_kg,
            "body_fat_pct_used": row.body_fat_pct_used,
            "explanation": row.explanation,
            "inputs": row.inputs,
            "created_at": row.created_at.astimezone(dt.UTC),
        }
    )


def _not_onboarded() -> ProblemError:
    return ProblemError(404, "not_onboarded", "Complete onboarding first.")


# ───────────── onboarding ─────────────


def is_onboarded(session: Session, user: User) -> bool:
    """Coaches have no wizard; athletes are onboarded once their profile exists."""
    if user.role == "coach":
        return True
    return session.get(AthleteProfile, user.id) is not None


def onboard(
    session: Session,
    user: User,
    request: OnboardingRequest,
    now: dt.datetime,
    telemetry: Telemetry,
) -> out.OnboardingResult:
    """Complete the wizard in one transaction (F2.1, F2.2 training and meal plan, F7, F2.6, D55)."""
    require_athlete(user)
    profile_in, metric_in = request.profile, request.body_metric
    # Serialises concurrent onboarding calls of the same athlete.
    session.execute(select(User.id).where(User.id == user.id).with_for_update()).one()
    if session.get(AthleteProfile, user.id) is not None:
        raise ProblemError(409, "already_onboarded", "You have already completed onboarding.")

    _check_body_metric(profile_in, metric_in)
    _check_avoided_exercises(session, user.id, profile_in.avoided_exercise_ids, "profile.")

    today = local_today(now, user.timezone)
    weight = _round(metric_in.weight_kg, 2)
    body_fat, method, navy_explanation, note = _body_fat_from_metric(profile_in, metric_in)

    # Plan first (pure), so its weekly kcal feeds the targets (F3.4) and is stored per
    # exercise and day (F13.2) at the weight just entered.
    generated, weekly, new_days = generate_training(session, profile_in, weight)
    targets_result = _compute_targets(
        telemetry,
        sex=profile_in.sex,
        height_cm=profile_in.height_cm,
        lifestyle=profile_in.lifestyle,
        goal=profile_in.goal,
        age_years=age_on(user.birth_date, today),
        weight_kg=weight,
        body_fat_pct=body_fat,
        planned_weekly_kcal_exact=weekly.weekly_kcal_exact,
        note=note,
    )

    profile_row = AthleteProfile(
        user_id=user.id,
        sex=profile_in.sex,
        height_cm=_round(profile_in.height_cm, 1),
        lifestyle=profile_in.lifestyle,
        goal=profile_in.goal,
        experience=profile_in.experience,
        days_per_week=profile_in.days_per_week,
        preferred_days=list(profile_in.preferred_days),
        session_minutes=profile_in.session_minutes,
        equipment=profile_in.equipment,
        avoided_exercise_ids=[str(i) for i in profile_in.avoided_exercise_ids],
        diet=profile_in.diet,
        allergies=list(profile_in.allergies),
        meals_per_day=profile_in.meals_per_day,
        created_at=now,
        updated_at=now,
    )
    session.add(profile_row)

    # D43: one entry per user and day; an entry logged earlier today is replaced.
    metric_row = session.scalar(
        select(BodyMetric).where(BodyMetric.user_id == user.id, BodyMetric.date == today)
    )
    if metric_row is None:
        metric_row = BodyMetric(user_id=user.id, date=today)
        session.add(metric_row)
    metric_row.weight_kg = weight
    metric_row.body_fat_pct = body_fat
    metric_row.bf_method = method
    metric_row.body_fat_explanation = navy_explanation
    metric_row.neck_cm = _round_opt(metric_in.neck_cm, 1)
    metric_row.waist_cm = _round_opt(metric_in.waist_cm, 1)
    metric_row.hip_cm = _round_opt(metric_in.hip_cm, 1)
    metric_row.created_at = now
    session.flush()

    targets_row = _store_targets(session, user.id, today, targets_result, now)

    # F7: the meal plan is generated with the training plan, from the targets just stored.
    generated_meals = meal_plans.generate(
        session,
        athlete_id=user.id,
        today=today,
        kcal=targets_row.kcal,
        protein_g=targets_row.protein_g,
        meals_per_day=profile_in.meals_per_day,
        diet=profile_in.diet,
        allergies=profile_in.allergies,
    )
    plan = create_plan_version(
        session,
        athlete_id=user.id,
        author_id=user.id,
        source="generated",
        days=new_days,
        now=now,
        meal_days=new_meal_days(generated_meals),
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProblemError(
            409, "already_onboarded", "You have already completed onboarding."
        ) from None

    return out.OnboardingResult(
        profile=_profile_view(profile_row),
        body_metric=_metric_view(metric_row),
        targets=_targets_view(targets_row),
        plan=plan_view(session, plan, _plan_warnings(generated)),
    )


def _plan_warnings(generated: GeneratedPlan) -> list[str]:
    return list(generated.warnings)


# ───────────── reads and profile update ─────────────


def get_profile(session: Session, athlete_id: uuid.UUID) -> out.AthleteProfile:
    row = session.get(AthleteProfile, athlete_id)
    if row is None:
        raise _not_onboarded()
    return _profile_view(row)


def targets_on(session: Session, athlete_id: uuid.UUID, day: dt.date) -> Targets | None:
    """The latest row with `valid_from <= day`; a day before the first row gets the first row."""
    rows = select(Targets).where(Targets.user_id == athlete_id)
    return session.scalar(
        rows.where(Targets.valid_from <= day).order_by(Targets.valid_from.desc()).limit(1)
    ) or session.scalar(rows.order_by(Targets.valid_from).limit(1))


def get_targets(
    session: Session, athlete_id: uuid.UUID, timezone: str, now: dt.datetime, on: dt.date | None
) -> out.Targets:
    """Targets valid on `on` (default: today in the athlete's time zone)."""
    row = targets_on(session, athlete_id, on or local_today(now, timezone))
    if row is None:
        raise _not_onboarded()
    return _targets_view(row)


def _latest_inputs(
    session: Session, athlete_id: uuid.UUID, today: dt.date
) -> tuple[float, float | None]:
    """Most recent weight and body fat on or before `today` (F13.2 convention)."""
    base = select(BodyMetric).where(BodyMetric.user_id == athlete_id, BodyMetric.date <= today)
    weight_row = session.scalar(
        base.where(BodyMetric.weight_kg.is_not(None)).order_by(BodyMetric.date.desc()).limit(1)
    )
    fat_row = session.scalar(
        base.where(BodyMetric.body_fat_pct.is_not(None)).order_by(BodyMetric.date.desc()).limit(1)
    )
    weight = weight_row.weight_kg if weight_row else None
    if weight is None:
        weight = session.scalar(
            select(Targets.weight_used_kg)
            .where(Targets.user_id == athlete_id)
            .order_by(Targets.valid_from.desc())
            .limit(1)
        )
    if weight is None:
        raise _not_onboarded()
    return float(weight), (fat_row.body_fat_pct if fat_row else None)


def _active_plan_weekly_kcal(session: Session, athlete_id: uuid.UUID, weight_kg: float) -> float:
    plan = session.scalar(
        select(Plan)
        .where(Plan.athlete_id == athlete_id, Plan.active.is_(True))
        .options(selectinload(Plan.training_days).selectinload(TrainingDay.exercises))
    )
    if plan is None:
        return 0.0
    exercise_ids = {e.exercise_id for d in plan.training_days for e in d.exercises}
    exercises = {
        e.id: e for e in session.scalars(select(Exercise).where(Exercise.id.in_(exercise_ids)))
    }
    return _weekly_kcal(
        [
            (
                day.weekday,
                [
                    (
                        exercises[e.exercise_id].type,
                        float(exercises[e.exercise_id].met),
                        e.sets,
                        e.rest_seconds,
                        e.target_seconds,
                    )
                    for e in day.exercises
                ],
            )
            for day in plan.training_days
        ],
        weight_kg,
    ).weekly_kcal_exact


def update_profile(
    session: Session,
    user: User,
    request: AthleteProfileInput,
    now: dt.datetime,
    telemetry: Telemetry,
) -> out.ProfileUpdateResult:
    """Replace the profile; recompute targets from today when a target-relevant field changed
    and keep the earlier `Targets` rows (D46). The training plan is not regenerated; meal portions
    are rescaled to the new kcal from today on (D74)."""
    require_athlete(user)
    session.execute(select(User.id).where(User.id == user.id).with_for_update()).one()
    row = session.get(AthleteProfile, user.id)
    if row is None:
        raise _not_onboarded()
    _check_avoided_exercises(session, user.id, request.avoided_exercise_ids, "")

    new_height = _round(request.height_cm, 1)
    changed = any(
        (new_height if name == "height_cm" else getattr(request, name)) != getattr(row, name)
        for name in TARGET_RELEVANT_FIELDS
    )
    row.sex = request.sex
    row.height_cm = new_height
    row.lifestyle = request.lifestyle
    row.goal = request.goal
    row.experience = request.experience
    row.days_per_week = request.days_per_week
    row.preferred_days = list(request.preferred_days)
    row.session_minutes = request.session_minutes
    row.equipment = request.equipment
    row.avoided_exercise_ids = [str(i) for i in request.avoided_exercise_ids]
    row.diet = request.diet
    row.allergies = list(request.allergies)
    row.meals_per_day = request.meals_per_day
    row.updated_at = now

    today = local_today(now, user.timezone)
    if changed:
        weight, body_fat = _latest_inputs(session, user.id, today)
        result = _compute_targets(
            telemetry,
            sex=row.sex,
            height_cm=row.height_cm,
            lifestyle=row.lifestyle,
            goal=row.goal,
            age_years=age_on(user.birth_date, today),
            weight_kg=weight,
            body_fat_pct=body_fat,
            planned_weekly_kcal_exact=_active_plan_weekly_kcal(session, user.id, weight),
            note=None,
        )
        targets_row = _store_targets(session, user.id, today, result, now)
        from app.services import portion_rescale  # late: plan_edit imports this module

        portion_rescale.rescale_future_meals(
            session,
            athlete=user,
            author=user,
            new_kcal=targets_row.kcal,
            now=now,
            reason="profile",
        )
    else:
        found = targets_on(session, user.id, today)
        if found is None:
            raise _not_onboarded()
        targets_row = found
    session.commit()
    return out.ProfileUpdateResult(
        profile=_profile_view(row), targets=_targets_view(targets_row), targets_changed=changed
    )
