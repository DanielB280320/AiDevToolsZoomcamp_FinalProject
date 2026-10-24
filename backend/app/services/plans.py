"""Training plan persistence and reads (spec §8, F8).

`create_plan_version` is the write path used by the generator flow (#25) and later by custom
edits: it stores a new version, deactivates the previous one and records a `PlanChange`, all in
the caller's transaction (it flushes, the caller commits). Inputs are plain dataclasses so this
module does not depend on the generator's output type.

Nothing here logs: plan content is health data (spec §6.5).
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.engines.exercise_kcal import duration_minutes, set_based_minutes
from app.errors import ProblemError
from app.models import Exercise, Plan, PlanChange, PlannedExercise, TrainingDay, User
from app.models.plan import WEEKDAYS
from app.schemas import plans as out
from app.schemas.users import UserRef

WARM_UP_MINUTES = 5  # D54: estimated session duration includes a 5 minute warm-up
CALIBRATION_HINT = "Choose a weight you can do for the target reps with 2 reps left"  # F5.4


@dataclass(frozen=True)
class NewPlannedExercise:
    exercise_id: uuid.UUID
    sets: int
    rest_seconds: int
    rule: str
    increment_kg: float
    reps_min: int | None = None
    reps_max: int | None = None
    target_weight_kg: float | None = None
    target_seconds: int | None = None
    deload_enabled: bool = True


@dataclass(frozen=True)
class NewTrainingDay:
    weekday: str
    name: str
    exercises: Sequence[NewPlannedExercise] = field(default_factory=tuple)


def create_plan_version(
    session: Session,
    *,
    athlete_id: uuid.UUID,
    author_id: uuid.UUID,
    source: str,
    days: Sequence[NewTrainingDay],
    now: dt.datetime,
) -> Plan:
    """Store `days` as the athlete's next plan version and make it the active one.

    `version = n + 1`; the previous active version is deactivated first so the partial unique
    index (one active plan per athlete) holds at every point. The athlete row is locked so two
    concurrent creations cannot pick the same version. Does not commit.
    """
    session.execute(select(User.id).where(User.id == athlete_id).with_for_update()).one()
    latest = session.scalar(select(func.max(Plan.version)).where(Plan.athlete_id == athlete_id))
    session.execute(
        update(Plan)
        .where(Plan.athlete_id == athlete_id, Plan.active.is_(True))
        .values(active=False)
    )
    plan = Plan(
        athlete_id=athlete_id,
        version=(latest or 0) + 1,
        source=source,
        active=True,
        revision=0,
        created_by=author_id,
        created_at=now,
        updated_at=now,
    )
    for day_order, day in enumerate(days):
        training_day = TrainingDay(weekday=day.weekday, name=day.name, position=day_order)
        for order, item in enumerate(day.exercises):
            training_day.exercises.append(
                PlannedExercise(
                    exercise_id=item.exercise_id,
                    position=order,
                    sets=item.sets,
                    reps_min=item.reps_min,
                    reps_max=item.reps_max,
                    target_weight_kg=item.target_weight_kg,
                    target_seconds=item.target_seconds,
                    rest_seconds=item.rest_seconds,
                    rule=item.rule,
                    increment_kg=item.increment_kg,
                    deload_enabled=item.deload_enabled,
                )
            )
        plan.training_days.append(training_day)
    session.add(plan)
    session.flush()
    session.add(
        PlanChange(
            plan_id=plan.id,
            author_id=author_id,
            change={"kind": "created", "version": plan.version, "source": source},
            created_at=now,
        )
    )
    session.flush()
    return plan


# ───────────── reads ─────────────


def resolve_athlete(user: User, athlete_id: str) -> uuid.UUID:
    """`me` or the caller's own id. Any other id is 403 `not_linked` (D41); the linked-coach
    case arrives with #47. A malformed id is a 400."""
    if athlete_id == "me":
        return user.id
    try:
        parsed = uuid.UUID(athlete_id)
    except ValueError:
        raise ProblemError(400, "bad_request", "The athlete id is invalid.") from None
    if parsed != user.id:
        raise ProblemError(403, "not_linked", "You do not have access to this athlete.")
    return parsed


def _ref(user: User) -> UserRef:
    return UserRef.model_validate(
        {"id": user.id, "display_name": user.display_name, "role": user.role}
    )


def _minutes(items: Sequence[tuple[PlannedExercise, Exercise]]) -> int:
    total = float(WARM_UP_MINUTES)
    for planned, exercise in items:
        if exercise.type == "timed":
            total += duration_minutes(planned.sets * (planned.target_seconds or 0))
        else:
            total += set_based_minutes(planned.sets, planned.rest_seconds)
    return round(total)


def get_active_plan(session: Session, athlete_id: uuid.UUID) -> out.Plan:
    plan = session.scalar(
        select(Plan)
        .where(Plan.athlete_id == athlete_id, Plan.active.is_(True))
        .options(selectinload(Plan.training_days).selectinload(TrainingDay.exercises))
    )
    if plan is None:
        raise ProblemError(
            404, "not_onboarded", "There is no plan yet. Complete onboarding to get one."
        )
    return _view(session, plan)


def _view(session: Session, plan: Plan) -> out.Plan:
    exercise_ids = {e.exercise_id for d in plan.training_days for e in d.exercises}
    exercises = {
        e.id: e for e in session.scalars(select(Exercise).where(Exercise.id.in_(exercise_ids)))
    }
    user_ids = {plan.created_by} | {d.edited_by for d in plan.training_days if d.edited_by}
    users = {u.id: u for u in session.scalars(select(User).where(User.id.in_(user_ids)))}
    order = {w: i for i, w in enumerate(WEEKDAYS)}
    days = sorted(plan.training_days, key=lambda d: (order[d.weekday], d.position))
    return out.Plan.model_validate(
        {
            "id": plan.id,
            "athlete_id": plan.athlete_id,
            "version": plan.version,
            "source": plan.source,
            "active": plan.active,
            "revision": plan.revision,
            "created_by": _ref(users[plan.created_by]),
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
            "training_days": [
                {
                    "id": day.id,
                    "weekday": day.weekday,
                    "name": day.name,
                    "order": day.position,
                    "exercises": [
                        _exercise_view(e, exercises[e.exercise_id]) for e in day.exercises
                    ],
                    "estimated_minutes": _minutes(
                        [(e, exercises[e.exercise_id]) for e in day.exercises]
                    ),
                    # Needs the athlete's body weight (F13.2); wired up with body metrics.
                    "planned_kcal": 0,
                    "edited_by": _ref(users[day.edited_by]) if day.edited_by else None,
                }
                for day in days
            ],
            "meal_days": [],
            "warnings": [],
        }
    )


def _exercise_view(planned: PlannedExercise, exercise: Exercise) -> dict[str, object]:
    return {
        "id": planned.id,
        "exercise": {
            "id": exercise.id,
            "name": exercise.name,
            "type": exercise.type,
            "equipment": exercise.equipment,
            "muscle_group": exercise.muscle_group,
        },
        "order": planned.position,
        "sets": planned.sets,
        "reps_min": planned.reps_min,
        "reps_max": planned.reps_max,
        "target_weight_kg": planned.target_weight_kg,
        "target_seconds": planned.target_seconds,
        "rest_seconds": planned.rest_seconds,
        "rule": planned.rule,
        "increment_kg": planned.increment_kg,
        "deload_enabled": planned.deload_enabled,
        "calibration_hint": (
            CALIBRATION_HINT
            if planned.target_weight_kg is None and exercise.type != "timed"
            else None
        ),
    }
