"""Custom-mode plan edits, regeneration and version reads (spec F8, D75).

Every edit stores a **new plan version** (source `custom`), like accepting a progression
suggestion does (D65): the previous version stays readable (F8.2) and finished or started
sessions keep pointing at the version they were performed against, so their targets never change
(F8.1, rule 7). Untouched planned sessions from today on move to the new version.

* Optimistic concurrency: the request carries the `revision` it read; the new version has
  `revision + 1`, so a stale client gets `409 plan_revision_conflict`. The athlete row is locked
  first, so two concurrent edits are serialised.
* Meals keep their `meal_key` (D73) when the request names an existing planned meal by `id`
  (reorder, replace in place, change grams or portion), so logs made today keep showing. A meal
  without `id` is new and gets a new key.
* Authorization: only the athlete may edit for now; `authorize_edit` is the single place where
  an active coach link (#46/#47) will be accepted.

Nothing here logs: plan content is health data (spec section 6.5).
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, selectinload

from app.errors import ProblemError
from app.models import (
    AthleteProfile,
    Exercise,
    Food,
    Meal,
    MealDay,
    MealItem,
    Plan,
    PlannedExercise,
    SetLog,
    Suggestion,
    TrainingDay,
    TrainingSession,
    User,
)
from app.models.plan import WEEKDAYS
from app.schemas import plans as schemas
from app.schemas.foods import FoodGrams
from app.schemas.problem import FieldError
from app.services import athlete as athlete_service
from app.services import meal_plans, plans
from app.services.clock import local_today
from app.services.plans import (
    NewMealDay,
    NewPlannedExercise,
    NewPlannedMeal,
    NewTrainingDay,
    create_plan_version,
    plan_view,
)


def authorize_edit(user: User, athlete_id: str) -> uuid.UUID:
    """The athlete whose plan `user` may change, else 403 `not_linked` (F8.4, D41).

    Today that is the athlete themselves. A coach with an active link to the athlete will be
    accepted here once coach links land (#46/#47); an unlinked coach or a stranger stays 403."""
    athlete = plans.resolve_athlete(user, athlete_id)
    if user.role != "athlete":
        raise ProblemError(403, "not_linked", "You do not have access to this athlete.")
    return athlete


def _invalid(*errors: FieldError) -> ProblemError:
    return ProblemError(422, "invalid_plan", "Some plan fields are invalid.", errors=errors)


def _error(field: str, code: str, message: str) -> FieldError:
    return FieldError(field=field, code=code, message=message)


def _lock_active(db: Session, athlete: uuid.UUID, revision: int | None) -> Plan:
    """Lock the athlete, then load the active plan and check the caller's `revision`."""
    db.execute(select(User.id).where(User.id == athlete).with_for_update()).one()
    plan = db.scalar(
        select(Plan)
        .where(Plan.athlete_id == athlete, Plan.active.is_(True))
        .options(
            selectinload(Plan.training_days).selectinload(TrainingDay.exercises),
            selectinload(Plan.meal_days).selectinload(MealDay.meals),
        )
    )
    if plan is None:
        raise ProblemError(
            404, "not_onboarded", "There is no plan yet. Complete onboarding to get one."
        )
    if revision is not None and revision != plan.revision:
        raise ProblemError(
            409,
            "plan_revision_conflict",
            "The plan changed since you loaded it. Reload it and apply your edit again.",
        )
    return plan


# ───────────── carry-over helpers ─────────────


def _carry_days(plan: Plan) -> list[NewTrainingDay]:
    return [
        NewTrainingDay(
            weekday=d.weekday,
            name=d.name,
            planned_kcal=d.planned_kcal,
            edited_by=d.edited_by,
            exercises=[_carry_exercise(e) for e in sorted(d.exercises, key=lambda e: e.position)],
        )
        for d in sorted(plan.training_days, key=lambda d: d.position)
    ]


def _carry_exercise(e: PlannedExercise) -> NewPlannedExercise:
    return NewPlannedExercise(
        exercise_id=e.exercise_id,
        sets=e.sets,
        rest_seconds=e.rest_seconds,
        rule=e.rule,
        increment_kg=e.increment_kg,
        reps_min=e.reps_min,
        reps_max=e.reps_max,
        target_weight_kg=e.target_weight_kg,
        target_seconds=e.target_seconds,
        deload_enabled=e.deload_enabled,
        planned_kcal=e.planned_kcal,
    )


def _exercise_signature(e: PlannedExercise | NewPlannedExercise) -> tuple[Any, ...]:
    return (
        e.exercise_id,
        e.sets,
        e.reps_min,
        e.reps_max,
        e.target_weight_kg,
        e.target_seconds,
        e.rest_seconds,
        e.rule,
        e.increment_kg,
        e.deload_enabled,
    )


def _finish(
    db: Session,
    *,
    athlete: User,
    author: User,
    old: Plan,
    new: Plan,
    now: dt.datetime,
    planned_map: dict[uuid.UUID, uuid.UUID],
) -> None:
    """Move untouched future sessions to `new` and settle pending suggestions of exercises
    that did not make it to the new version."""
    new.updated_at = now
    _rebase_sessions(db, athlete, new, now)
    old_ids = {e.id for d in old.training_days for e in d.exercises}
    for pending in db.scalars(
        select(Suggestion).where(
            Suggestion.athlete_id == athlete.id,
            Suggestion.kind == "progression",
            Suggestion.status == "pending",
            Suggestion.planned_exercise_id.in_(old_ids or {uuid.uuid4()}),
        )
    ):
        target = (
            planned_map.get(pending.planned_exercise_id) if pending.planned_exercise_id else None
        )
        if target is not None:
            pending.planned_exercise_id = target
            pending.payload = {**pending.payload, "planned_exercise_id": str(target)}
        else:  # the exercise was removed or replaced: the suggestion no longer applies
            pending.status = "rejected"
            pending.decided_by = author.id
            pending.decided_at = now


def _rebase_sessions(db: Session, athlete: User, new: Plan, now: dt.datetime) -> None:
    """Untouched `planned` sessions from today on follow the new template (F8.1). Sessions with
    logs, started or finished, and every session before today stay on their version. A session
    whose weekday is no longer a training day is dropped (it was never logged)."""
    today = local_today(now, athlete.timezone)
    by_weekday: dict[str, TrainingDay] = {}
    for day in new.training_days:
        by_weekday.setdefault(day.weekday, day)
    logged = exists().where(SetLog.session_id == TrainingSession.id)
    for row in db.scalars(
        select(TrainingSession).where(
            TrainingSession.athlete_id == athlete.id,
            TrainingSession.status == "planned",
            TrainingSession.date >= today,
            TrainingSession.plan_id != new.id,
            ~logged,
        )
    ):
        template_day = by_weekday.get(WEEKDAYS[(row.original_date or row.date).weekday()])
        if template_day is None:
            db.delete(row)
        else:
            row.plan_id = new.id
            row.training_day_id = template_day.id


def _planned_map(old: Plan, new: Plan) -> dict[uuid.UUID, uuid.UUID]:
    """Old -> new planned exercise ids when `new` carries `old`'s training days unchanged."""
    result: dict[uuid.UUID, uuid.UUID] = {}
    olds = sorted(old.training_days, key=lambda d: d.position)
    news = sorted(new.training_days, key=lambda d: d.position)
    for o, n in zip(olds, news, strict=True):
        for oe, ne in zip(
            sorted(o.exercises, key=lambda e: e.position),
            sorted(n.exercises, key=lambda e: e.position),
            strict=True,
        ):
            result[oe.id] = ne.id
    return result


# ───────────── training edit ─────────────


def _validate_training(
    db: Session, athlete: uuid.UUID, old: Plan, body: schemas.TrainingPlanUpdate
) -> dict[uuid.UUID, Exercise]:
    errors: list[FieldError] = []
    day_ids = {d.id for d in old.training_days}
    planned_ids = {e.id for d in old.training_days for e in d.exercises}
    wanted = {e.exercise_id for d in body.training_days for e in d.exercises}
    known = {
        e.id: e
        for e in db.scalars(
            select(Exercise).where(
                Exercise.id.in_(wanted),
                (Exercise.owner_id.is_(None)) | (Exercise.owner_id == athlete),
            )
        )
    }
    seen_weekdays: set[str] = set()
    seen_days: set[uuid.UUID] = set()
    seen_planned: set[uuid.UUID] = set()
    for i, day in enumerate(body.training_days):
        path = f"training_days[{i}]"
        if day.weekday in seen_weekdays:
            errors.append(_error(f"{path}.weekday", "duplicate", "One training day per weekday."))
        seen_weekdays.add(day.weekday)
        if day.id is not None:
            if day.id not in day_ids or day.id in seen_days:
                errors.append(
                    _error(f"{path}.id", "unknown_id", "Not a training day of this plan.")
                )
            seen_days.add(day.id)
        for j, item in enumerate(day.exercises):
            field = f"{path}.exercises[{j}]"
            if item.id is not None:
                if item.id not in planned_ids or item.id in seen_planned:
                    errors.append(
                        _error(f"{field}.id", "unknown_id", "Not an exercise of this plan.")
                    )
                seen_planned.add(item.id)
            exercise = known.get(item.exercise_id)
            if exercise is None:
                errors.append(
                    _error(f"{field}.exercise_id", "unknown_exercise", "Unknown exercise.")
                )
                continue
            errors.extend(_check_targets(field, item, exercise))
    if errors:
        raise _invalid(*errors)
    return known


def _check_targets(
    field: str, item: schemas.PlannedExerciseInput, exercise: Exercise
) -> list[FieldError]:
    """Targets must fit the exercise type (strength/bodyweight: reps; timed: seconds, D65)."""
    errors: list[FieldError] = []
    if exercise.type == "timed":
        if item.target_seconds is None:
            errors.append(
                _error(f"{field}.target_seconds", "required", "A timed exercise needs seconds.")
            )
        if (
            item.reps_min is not None
            or item.reps_max is not None
            or item.target_weight_kg is not None
        ):
            errors.append(_error(field, "invalid_targets", "A timed exercise has seconds only."))
        return errors
    if item.reps_min is None:
        errors.append(_error(f"{field}.reps_min", "required", "Set the target reps."))
    if item.target_seconds is not None:
        errors.append(
            _error(f"{field}.target_seconds", "invalid_targets", "Seconds are for timed exercises.")
        )
    if item.reps_min is not None and item.reps_max is not None:
        if item.reps_max < item.reps_min:
            errors.append(_error(f"{field}.reps_max", "out_of_range", "Must be at least reps_min."))
        elif item.rule == "linear" and item.reps_max != item.reps_min:
            errors.append(
                _error(
                    f"{field}.reps_max",
                    "invalid_targets",
                    "Linear progression uses one rep target.",
                )
            )
    return errors


def update_training(
    db: Session,
    user: User,
    athlete_id: str,
    body: schemas.TrainingPlanUpdate,
    now: dt.datetime,
) -> schemas.Plan:
    athlete_uuid = authorize_edit(user, athlete_id)
    old = _lock_active(db, athlete_uuid, body.revision)
    athlete = db.get(User, athlete_uuid)
    assert athlete is not None  # noqa: S101 - the plan's owner exists
    exercises = _validate_training(db, athlete_uuid, old, body)

    old_days = {d.id: d for d in old.training_days}
    old_planned = {e.id: e for d in old.training_days for e in d.exercises}
    day_inputs: list[tuple[schemas.TrainingDayInput, TrainingDay | None, bool]] = []
    built: list[list[NewPlannedExercise]] = []
    for day in body.training_days:
        items = [
            NewPlannedExercise(
                exercise_id=e.exercise_id,
                sets=e.sets,
                rest_seconds=e.rest_seconds,
                rule=e.rule,
                increment_kg=(
                    e.increment_kg
                    if e.increment_kg is not None
                    else float(exercises[e.exercise_id].increment_kg)
                ),
                reps_min=e.reps_min,
                reps_max=e.reps_max if e.reps_max is not None else e.reps_min,
                target_weight_kg=e.target_weight_kg,
                target_seconds=e.target_seconds,
                deload_enabled=e.deload_enabled,
            )
            for e in day.exercises
        ]
        previous = old_days.get(day.id) if day.id else None
        unchanged = (
            previous is not None
            and previous.weekday == day.weekday
            and previous.name == day.name
            and [
                _exercise_signature(e) for e in sorted(previous.exercises, key=lambda e: e.position)
            ]
            == [_exercise_signature(i) for i in items]
        )
        day_inputs.append((day, previous, unchanged))
        built.append(items)

    # F13.2: changed and new days are priced at the athlete's current weight; untouched days keep
    # the estimate they were stored with.
    weight, _ = athlete_service._latest_inputs(db, athlete_uuid, local_today(now, athlete.timezone))
    changed = [n for n, (_, _, unchanged) in enumerate(day_inputs) if not unchanged]
    priced = athlete_service._weekly_kcal(
        [
            (
                body.training_days[n].weekday,
                [
                    (
                        exercises[i.exercise_id].type,
                        float(exercises[i.exercise_id].met),
                        i.sets,
                        i.rest_seconds,
                        i.target_seconds,
                    )
                    for i in built[n]
                ],
            )
            for n in changed
        ],
        weight,
    )
    new_days: list[NewTrainingDay] = []
    for n, (day, previous, unchanged) in enumerate(day_inputs):
        if unchanged:
            assert previous is not None  # noqa: S101
            new_days.append(
                NewTrainingDay(
                    day.weekday,
                    day.name,
                    [
                        _carry_exercise(e)
                        for e in sorted(previous.exercises, key=lambda e: e.position)
                    ],
                    previous.planned_kcal,
                    previous.edited_by,
                )
            )
            continue
        day_kcal = priced.days[changed.index(n)]
        new_days.append(
            NewTrainingDay(
                day.weekday,
                day.name,
                [
                    _with_kcal(item, part.kcal)
                    for item, part in zip(built[n], day_kcal.parts, strict=True)
                ],
                day_kcal.kcal,
                user.id,
            )
        )

    new = create_plan_version(
        db,
        athlete_id=athlete_uuid,
        author_id=user.id,
        source="custom",
        days=new_days,
        now=now,
        revision=old.revision + 1,
        change={
            "kind": "training_edited",
            "days": len(new_days),
            "exercises": sum(len(d.exercises) for d in new_days),
        },
    )
    planned_map: dict[uuid.UUID, uuid.UUID] = {}
    for day, created in zip(body.training_days, new.training_days, strict=True):
        for item, row in zip(day.exercises, created.exercises, strict=True):
            before = old_planned.get(item.id) if item.id else None
            if before is not None and before.exercise_id == item.exercise_id:
                planned_map[before.id] = row.id
    _finish(db, athlete=athlete, author=user, old=old, new=new, now=now, planned_map=planned_map)
    db.commit()
    return plan_view(db, new)


def _with_kcal(item: NewPlannedExercise, kcal: int) -> NewPlannedExercise:
    return NewPlannedExercise(
        exercise_id=item.exercise_id,
        sets=item.sets,
        rest_seconds=item.rest_seconds,
        rule=item.rule,
        increment_kg=item.increment_kg,
        reps_min=item.reps_min,
        reps_max=item.reps_max,
        target_weight_kg=item.target_weight_kg,
        target_seconds=item.target_seconds,
        deload_enabled=item.deload_enabled,
        planned_kcal=kcal,
    )


# ───────────── meal edit ─────────────


def _validate_meals(
    db: Session, athlete: uuid.UUID, old: Plan, body: schemas.MealPlanUpdate
) -> tuple[dict[uuid.UUID, Meal], dict[uuid.UUID, Food]]:
    errors: list[FieldError] = []
    planned_ids = {m.id for d in old.meal_days for m in d.meals}
    meal_ids = {m.meal_id for d in body.meal_days for m in d.meals}
    food_ids = {g.food_id for d in body.meal_days for m in d.meals for g in (m.items or [])}
    meals = {
        m.id: m
        for m in db.scalars(
            select(Meal).where(
                Meal.id.in_(meal_ids), (Meal.owner_id.is_(None)) | (Meal.owner_id == athlete)
            )
        )
    }
    foods = {
        f.id: f
        for f in db.scalars(
            select(Food).where(
                Food.id.in_(food_ids), (Food.owner_id.is_(None)) | (Food.owner_id == athlete)
            )
        )
    }
    seen_weekdays: set[str] = set()
    seen_planned: set[uuid.UUID] = set()
    for i, day in enumerate(body.meal_days):
        path = f"meal_days[{i}]"
        if day.weekday in seen_weekdays:
            errors.append(_error(f"{path}.weekday", "duplicate", "One meal day per weekday."))
        seen_weekdays.add(day.weekday)
        for j, item in enumerate(day.meals):
            field = f"{path}.meals[{j}]"
            if item.id is not None:
                if item.id not in planned_ids or item.id in seen_planned:
                    errors.append(_error(f"{field}.id", "unknown_id", "Not a meal of this plan."))
                seen_planned.add(item.id)
            if item.meal_id not in meals:
                errors.append(_error(f"{field}.meal_id", "unknown_meal", "Unknown meal."))
            for k, grams in enumerate(item.items or []):
                if grams.food_id not in foods:
                    errors.append(
                        _error(f"{field}.items[{k}].food_id", "unknown_food", "Unknown food.")
                    )
    if errors:
        raise _invalid(*errors)
    return meals, foods


def _meal_for(
    db: Session,
    athlete: uuid.UUID,
    base: Meal,
    items: Sequence[FoodGrams] | None,
) -> uuid.UUID:
    """The meal to plan: `base`, or a private copy with the given grams (the shared library
    meal is never changed). Grams equal to the base meal's reuse it, so repeated saves do not pile
    up copies."""
    if items is None:
        return base.id
    wanted = [(g.food_id, g.grams) for g in items]
    current = [
        (i.food_id, float(i.grams))
        for i in db.scalars(
            select(MealItem).where(MealItem.meal_id == base.id).order_by(MealItem.position)
        )
    ]
    if wanted == current:
        return base.id
    copy = Meal(owner_id=athlete, source="custom", name=base.name, slots=list(base.slots))
    db.add(copy)
    db.flush()
    for position, (food_id, grams) in enumerate(wanted):
        db.add(MealItem(meal_id=copy.id, food_id=food_id, position=position, grams=grams))
    return copy.id


def update_meals(
    db: Session,
    user: User,
    athlete_id: str,
    body: schemas.MealPlanUpdate,
    now: dt.datetime,
) -> schemas.Plan:
    athlete_uuid = authorize_edit(user, athlete_id)
    old = _lock_active(db, athlete_uuid, body.revision)
    athlete = db.get(User, athlete_uuid)
    assert athlete is not None  # noqa: S101
    meals, _ = _validate_meals(db, athlete_uuid, old, body)

    old_planned = {m.id: m for d in old.meal_days for m in d.meals}
    old_days = {d.weekday: d for d in old.meal_days}
    new_days: list[NewMealDay] = []
    for day in body.meal_days:
        built: list[NewPlannedMeal] = []
        for item in day.meals:
            before = old_planned.get(item.id) if item.id else None
            meal_id = _meal_for(db, athlete_uuid, meals[item.meal_id], item.items)
            built.append(
                NewPlannedMeal(
                    slot=item.slot,
                    meal_id=meal_id,
                    # Grams given: they are final amounts, so the copy is planned at 1x.
                    portion_factor=1.0 if item.items else item.portion_factor,
                    # D73: an existing planned meal keeps its key (and so its logs).
                    meal_key=before.meal_key if before else None,
                )
            )
        previous = old_days.get(day.weekday)
        same = previous is not None and [
            (m.slot, m.meal_id, float(m.portion_factor))
            for m in sorted(previous.meals, key=lambda m: m.position)
        ] == [(m.slot, m.meal_id, float(m.portion_factor)) for m in built]
        keys_same = (
            same
            and previous is not None
            and [m.meal_key for m in sorted(previous.meals, key=lambda m: m.position)]
            == [m.meal_key for m in built]
        )
        if previous is not None and same and keys_same:
            new_days.append(NewMealDay(day.weekday, built, previous.warning, previous.edited_by))
        else:
            new_days.append(NewMealDay(day.weekday, built, None, user.id))

    new = create_plan_version(
        db,
        athlete_id=athlete_uuid,
        author_id=user.id,
        source="custom",
        days=_carry_days(old),
        meal_days=new_days,
        now=now,
        revision=old.revision + 1,
        change={
            "kind": "meals_edited",
            "days": len(new_days),
            "meals": sum(len(d.meals) for d in new_days),
        },
    )
    _finish(
        db,
        athlete=athlete,
        author=user,
        old=old,
        new=new,
        now=now,
        planned_map=_planned_map(old, new),
    )
    db.commit()
    return plan_view(db, new)


# ───────────── regenerate ─────────────


def regenerate(
    db: Session, user: User, athlete_id: str, scope: str, now: dt.datetime
) -> schemas.Plan:
    """A new `generated` version from the current profile and targets (F8.2). The part outside
    `scope` is copied from the current version. Regenerated meals are new meals (new keys), so
    logs of the replaced meals stay visible as extra meal logs (D73)."""
    athlete_uuid = authorize_edit(user, athlete_id)
    old = _lock_active(db, athlete_uuid, None)
    athlete = db.get(User, athlete_uuid)
    assert athlete is not None  # noqa: S101
    profile = db.get(AthleteProfile, athlete_uuid)
    today = local_today(now, athlete.timezone)
    targets = athlete_service.targets_on(db, athlete_uuid, today)
    if profile is None or targets is None:
        raise ProblemError(
            404, "not_onboarded", "There is no plan yet. Complete onboarding to get one."
        )
    warnings: list[str] = []
    days = _carry_days(old)
    meal_days: list[NewMealDay] | None = None
    if scope in ("all", "training"):
        weight, _ = athlete_service._latest_inputs(db, athlete_uuid, today)
        generated, _, days = athlete_service.generate_training(db, profile, weight)
        warnings = list(generated.warnings)
    if scope in ("all", "meals"):
        meal_days = athlete_service.new_meal_days(
            meal_plans.generate(
                db,
                athlete_id=athlete_uuid,
                today=today,
                kcal=targets.kcal,
                protein_g=targets.protein_g,
                meals_per_day=profile.meals_per_day,
                diet=profile.diet,
                allergies=profile.allergies,
            )
        )
    new = create_plan_version(
        db,
        athlete_id=athlete_uuid,
        author_id=user.id,
        source="generated",
        days=days,
        meal_days=meal_days,
        now=now,
        revision=old.revision + 1,
        change={"kind": "regenerated", "scope": scope},
    )
    _finish(
        db,
        athlete=athlete,
        author=user,
        old=old,
        new=new,
        now=now,
        planned_map=_planned_map(old, new) if scope == "meals" else {},
    )
    db.commit()
    return plan_view(db, new, warnings)


# ───────────── versions ─────────────


def _summary(plan: Plan, users: dict[uuid.UUID, User]) -> schemas.PlanVersionSummary:
    return schemas.PlanVersionSummary.model_validate(
        {
            "id": plan.id,
            "version": plan.version,
            "source": plan.source,
            "active": plan.active,
            "created_by": plans.user_ref(users[plan.created_by]) if plan.created_by else None,
            "created_at": plan.created_at,
        }
    )


def list_versions(db: Session, athlete: uuid.UUID) -> schemas.PlanVersionList:
    rows = list(
        db.scalars(select(Plan).where(Plan.athlete_id == athlete).order_by(Plan.version.desc()))
    )
    ids = {p.created_by for p in rows if p.created_by}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}
    return schemas.PlanVersionList(items=[_summary(p, users) for p in rows])


def get_version(db: Session, athlete: uuid.UUID, version: int) -> schemas.Plan:
    plan = db.scalar(
        select(Plan)
        .where(Plan.athlete_id == athlete, Plan.version == version)
        .options(
            selectinload(Plan.training_days).selectinload(TrainingDay.exercises),
            selectinload(Plan.meal_days).selectinload(MealDay.meals),
        )
    )
    if plan is None:
        raise ProblemError(404, "not_found", "That plan version does not exist.")
    return plan_view(db, plan)


__all__ = [
    "authorize_edit",
    "get_version",
    "list_versions",
    "regenerate",
    "update_meals",
    "update_training",
]
