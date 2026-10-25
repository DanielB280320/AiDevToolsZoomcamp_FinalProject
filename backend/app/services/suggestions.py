"""Suggestions (spec F11): persistence of engine output, the finish hook, list, accept, reject.

* Finishing a session (and editing a finished one inside its window, F10.3) runs the progression
  engine for every performed exercise whose rule is not `manual` and stores one `pending`
  suggestion each, with the engine's `rule`, `inputs` and `reason` (F11.4). Re-running replaces
  the session's still-pending suggestions; decided ones are never touched.
* The engine version comes from the `progression_engine` flag (F11.5). Only `v1` exists, so any
  other value (including a stored unknown one) runs `v1`.
* Accepting writes the accepted (or edited) values onto the planned exercise, which is where
  future sessions read their targets. Set logs keep their own target snapshots (rule 7).
* Rejecting changes nothing but the suggestion. The next finished session of the exercise
  simply produces a fresh pending suggestion.
* Only the athlete decides until coach linking lands (#47). Another athlete's suggestion, and an
  unknown id, are `403 not_linked` (D41).

Nothing here logs: targets, reps and reasons are health data (spec section 6.5).
"""

import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engines import progression
from app.engines.progression import LoggedSet, ProgressionInput
from app.errors import ProblemError
from app.models import (
    Exercise,
    Plan,
    PlanChange,
    PlannedExercise,
    SetLog,
    TrainingDay,
    TrainingSession,
    User,
)
from app.models import Suggestion as Row
from app.schemas import suggestions as out
from app.schemas.users import UserRef
from app.telemetry.metrics import SuggestionRule

Engine = Callable[[ProgressionInput], progression.Suggestion]
ENGINES: dict[str, Engine] = {"v1": progression.suggest}
DEFAULT_ENGINE = "v1"

_TARGET_KEYS = ("target_weight_kg", "reps_min", "reps_max", "target_seconds")


def engine_for(version: str) -> Engine:
    """The engine for a `progression_engine` flag value; unknown or unbuilt versions run v1."""
    return ENGINES.get(version, ENGINES[DEFAULT_ENGINE])


def api_rule(exercise_type: str, rule: str, action: str) -> SuggestionRule:
    """The contract's `SuggestionRule` (also the metric label) for one engine result."""
    if action == "deload":
        return "deload"
    if action == "calibrate":
        return "calibration"
    if exercise_type == "timed":
        return "timed"
    if exercise_type == "bodyweight":
        return "bodyweight"
    return "double" if rule == "double" else "linear"


# ───────────── views ─────────────


def view(db: Session, row: Row) -> out.Suggestion:
    decider = db.get(User, row.decided_by) if row.decided_by else None
    return out.Suggestion(
        id=row.id,
        athlete_id=row.athlete_id,
        kind=row.kind,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        rule=row.rule,  # type: ignore[arg-type]
        reason=row.reason,
        inputs=row.inputs,
        payload=row.payload,
        created_at=row.created_at,
        decided_by=None
        if decider is None
        else UserRef.model_validate(
            {"id": decider.id, "display_name": decider.display_name, "role": decider.role}
        ),
        decided_at=row.decided_at,
    )


def pending_by_planned_exercise(
    db: Session, athlete_id: uuid.UUID, planned_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """The newest pending progression suggestion per planned exercise (session banner, F11)."""
    if not planned_ids:
        return {}
    rows = db.execute(
        select(Row.planned_exercise_id, Row.id)
        .where(
            Row.athlete_id == athlete_id,
            Row.kind == "progression",
            Row.status == "pending",
            Row.planned_exercise_id.in_(planned_ids),
        )
        .order_by(Row.created_at, Row.id)
    ).all()
    return {planned: sid for planned, sid in rows if planned is not None}


# ───────────── generation (finish hook, F10.3 recompute) ─────────────


def _targets(
    weight: float | None, reps_min: int | None, reps_max: int | None, seconds: int | None
) -> dict[str, Any]:
    return {
        "target_weight_kg": weight,
        "reps_min": reps_min,
        "reps_max": reps_max,
        "target_seconds": seconds,
    }


def _previous_failures(db: Session, row: TrainingSession, exercise_id: uuid.UUID) -> int:
    """The failure counter after the athlete's latest earlier session of this exercise."""
    previous = db.scalar(
        select(Row.inputs)
        .join(TrainingSession, TrainingSession.id == Row.session_id)
        .where(
            Row.athlete_id == row.athlete_id,
            Row.kind == "progression",
            Row.exercise_id == exercise_id,
            TrainingSession.date < row.date,
        )
        .order_by(TrainingSession.date.desc(), Row.created_at.desc())
        .limit(1)
    )
    return int((previous or {}).get("consecutive_failures_after", 0))


def _is_first_session(db: Session, row: TrainingSession, exercise_id: uuid.UUID) -> bool:
    earlier = db.scalar(
        select(SetLog.id)
        .join(TrainingSession, TrainingSession.id == SetLog.session_id)
        .where(
            TrainingSession.athlete_id == row.athlete_id,
            TrainingSession.id != row.id,
            TrainingSession.status == "done",
            TrainingSession.date < row.date,
            SetLog.exercise_id == exercise_id,
            SetLog.skipped.is_(False),
        )
        .limit(1)
    )
    return earlier is None


def refresh_for_session(
    db: Session, user: User, session_id: uuid.UUID, engine_version: str, now: dt.datetime
) -> list[Row]:
    """Replace the finished session's pending suggestions with freshly computed ones.

    Returns the new rows (empty if the session is not finished). Commits."""
    session = db.scalar(
        select(TrainingSession)
        .where(TrainingSession.id == session_id, TrainingSession.athlete_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None or session.status != "done":
        return []
    engine = engine_for(engine_version)
    version = engine_version if engine_version in ENGINES else DEFAULT_ENGINE
    day = db.get(TrainingDay, session.training_day_id)
    assert day is not None  # noqa: S101 - FK guarantees it
    planned_list = list(day.exercises)
    exercises = {
        e.id: e
        for e in db.scalars(
            select(Exercise).where(Exercise.id.in_({p.exercise_id for p in planned_list}))
        )
    }
    logs_by_exercise: dict[uuid.UUID, list[SetLog]] = defaultdict(list)
    for log in db.scalars(
        select(SetLog).where(SetLog.session_id == session.id).order_by(SetLog.set_no)
    ):
        logs_by_exercise[log.exercise_id].append(log)

    decided = set(
        db.scalars(
            select(Row.planned_exercise_id).where(
                Row.session_id == session.id, Row.kind == "progression", Row.status != "pending"
            )
        )
    )
    db.execute(
        delete(Row).where(
            Row.session_id == session.id, Row.kind == "progression", Row.status == "pending"
        )
    )

    created: list[Row] = []
    for planned in planned_list:
        logs = [log for log in logs_by_exercise.get(planned.exercise_id, []) if not log.skipped]
        if planned.rule == "manual" or not logs or planned.id in decided:
            continue
        exercise = exercises[planned.exercise_id]
        first = logs[0]
        timed = exercise.type == "timed"
        # The engine judges the session against the targets it was performed against.
        target_weight = first.target_weight_kg
        target_reps = first.target_reps if first.target_reps is not None else planned.reps_min
        target_seconds = (
            first.target_seconds if first.target_seconds is not None else planned.target_seconds
        )
        data = ProgressionInput(
            exercise_type=exercise.type,  # type: ignore[arg-type]
            rule=planned.rule,  # type: ignore[arg-type]
            equipment=exercise.equipment,
            sets_planned=planned.sets,
            logged_sets=[LoggedSet(x.reps, x.weight_kg, x.seconds, True) for x in logs],
            target_weight_kg=target_weight,
            target_reps=target_reps,
            reps_min=target_reps,
            reps_max=planned.reps_max,
            target_seconds=target_seconds,
            increment_kg=planned.increment_kg,
            deload_enabled=planned.deload_enabled,
            consecutive_failures=_previous_failures(db, session, exercise.id),
            is_first_session=_is_first_session(db, session, exercise.id),
            allows_added_weight=exercise.allows_added_weight,
            imperial=user.units == "imperial",
            region=exercise.region,
        )
        result = engine(data)
        if result.action == "none":
            continue
        current = _targets(
            planned.target_weight_kg, planned.reps_min, planned.reps_max, planned.target_seconds
        )
        proposed = dict(current)
        if timed:
            proposed["target_seconds"] = result.seconds or current["target_seconds"]
        else:
            if result.weight_kg is not None:
                proposed["target_weight_kg"] = result.weight_kg
            if result.reps is not None:
                proposed["reps_min"] = result.reps
                if planned.rule == "linear" or (
                    proposed["reps_max"] is not None and result.reps > proposed["reps_max"]
                ):
                    proposed["reps_max"] = result.reps
        rule = api_rule(exercise.type, planned.rule, result.action)
        suggestion = Row(
            athlete_id=session.athlete_id,
            kind="progression",
            status="pending",
            rule=rule,
            reason=result.reason,
            inputs={
                **result.inputs,
                "engine_version": version,
                "action": result.action,
                "consecutive_failures_after": result.consecutive_failures,
            },
            payload={
                "exercise": {
                    "id": str(exercise.id),
                    "name": exercise.name,
                    "type": exercise.type,
                    "equipment": exercise.equipment,
                    "muscle_group": exercise.muscle_group,
                },
                "planned_exercise_id": str(planned.id),
                "source_session_id": str(session.id),
                "current": current,
                "proposed": proposed,
                "hint": "Ready for a harder variation"
                if result.action == "harder_variation"
                else None,
                "applied": None,
            },
            session_id=session.id,
            planned_exercise_id=planned.id,
            exercise_id=exercise.id,
            created_at=now,
        )
        db.add(suggestion)
        created.append(suggestion)
    db.commit()
    return created


# ───────────── list ─────────────


def list_suggestions(
    db: Session, athlete_id: uuid.UUID, status: str, kind: str | None
) -> out.SuggestionList:
    query = select(Row).where(Row.athlete_id == athlete_id, Row.status == status)
    if kind is not None:
        query = query.where(Row.kind == kind)
    rows = db.scalars(query.order_by(Row.created_at.desc(), Row.id.desc()))
    return out.SuggestionList(items=[view(db, r) for r in rows])


# ───────────── decide ─────────────


def _locked(db: Session, user: User, suggestion_id: uuid.UUID) -> Row:
    row = db.scalar(
        select(Row)
        .where(Row.id == suggestion_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.athlete_id != user.id:
        raise ProblemError(403, "not_linked", "You do not have access to this athlete.")
    if row.status != "pending":
        raise ProblemError(
            409, "suggestion_already_decided", "This suggestion has already been decided."
        )
    return row


def _invalid(detail: str) -> ProblemError:
    return ProblemError(422, "invalid_overrides", detail)


def _applied(row: Row, overrides: out.SuggestionOverrides | None) -> dict[str, Any]:
    """The proposed targets with the edit-then-accept overrides applied and validated."""
    applied: dict[str, Any] = dict(row.payload["proposed"])
    if overrides is None:
        return applied
    given = overrides.model_fields_set
    if row.kind != "progression" or "kcal" in given:
        raise _invalid("These overrides do not match the kind of this suggestion.")
    timed = row.payload["exercise"]["type"] == "timed"
    allowed = {"target_seconds"} if timed else {"target_weight_kg", "reps_min", "reps_max"}
    if not given <= allowed:
        kind = row.payload["exercise"]["type"]
        raise _invalid(f"A {kind} exercise accepts only {sorted(allowed)}.")
    for key in given:
        applied[key] = getattr(overrides, key)
    if row.inputs.get("rule") == "linear" and given & {"reps_min", "reps_max"}:
        # Linear exercises have one fixed rep target.
        reps = overrides.reps_min if "reps_min" in given else overrides.reps_max
        other = overrides.reps_max if "reps_max" in given else overrides.reps_min
        if other is not None and other != reps:
            raise _invalid("A linear exercise has one rep target: reps_min must equal reps_max.")
        applied["reps_min"] = applied["reps_max"] = reps
    low, high = applied["reps_min"], applied["reps_max"]
    if low is not None and high is not None and high < low:
        raise _invalid("reps_max must not be below reps_min.")
    return applied


def _target_planned(db: Session, row: Row) -> PlannedExercise | None:
    """The planned exercise to update: the suggestion's own if its plan is still active, else
    the same exercise on the same weekday of the active plan."""
    planned = db.get(PlannedExercise, row.planned_exercise_id) if row.planned_exercise_id else None
    if planned is None:
        return None
    day = db.get(TrainingDay, planned.training_day_id)
    assert day is not None  # noqa: S101 - FK guarantees it
    plan = db.get(Plan, day.plan_id)
    assert plan is not None  # noqa: S101 - FK guarantees it
    if plan.active:
        return planned
    return db.scalar(
        select(PlannedExercise)
        .join(TrainingDay, TrainingDay.id == PlannedExercise.training_day_id)
        .join(Plan, Plan.id == TrainingDay.plan_id)
        .where(
            Plan.athlete_id == row.athlete_id,
            Plan.active.is_(True),
            TrainingDay.weekday == day.weekday,
            PlannedExercise.exercise_id == planned.exercise_id,
        )
        .limit(1)
    )


def accept(
    db: Session,
    user: User,
    suggestion_id: uuid.UUID,
    overrides: out.SuggestionOverrides | None,
    now: dt.datetime,
) -> Row:
    row = _locked(db, user, suggestion_id)
    applied = _applied(row, overrides)
    target = _target_planned(db, row)
    if target is not None:
        if row.payload["exercise"]["type"] == "timed":
            target.target_seconds = applied["target_seconds"]
        else:
            target.target_weight_kg = applied["target_weight_kg"]
            target.reps_min = applied["reps_min"]
            target.reps_max = applied["reps_max"]
        day = db.get(TrainingDay, target.training_day_id)
        assert day is not None  # noqa: S101 - FK guarantees it
        plan = db.get(Plan, day.plan_id)
        assert plan is not None  # noqa: S101 - FK guarantees it
        plan.revision += 1
        plan.updated_at = now
        db.add(
            PlanChange(
                plan_id=plan.id,
                author_id=user.id,
                change={"kind": "suggestion_accepted", "suggestion_id": str(row.id)},
                created_at=now,
            )
        )
    row.payload = {**row.payload, "applied": applied}
    row.status = "accepted"
    row.decided_by = user.id
    row.decided_at = now
    db.commit()
    return row


def reject(db: Session, user: User, suggestion_id: uuid.UUID, now: dt.datetime) -> Row:
    row = _locked(db, user, suggestion_id)
    row.status = "rejected"
    row.decided_by = user.id
    row.decided_at = now
    db.commit()
    return row
