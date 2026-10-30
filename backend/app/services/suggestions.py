"""Suggestions (spec F11): persistence of engine output, the finish hook, list, accept, reject.

* Finishing a session (and editing a finished one inside its window, F10.3) runs the progression
  engine for every performed exercise whose rule is not `manual` and stores one `pending`
  suggestion each, with the engine's `rule`, `inputs` and `reason` (F11.4). Re-running replaces
  the session's still-pending suggestions; decided ones are never touched.
* The engine version comes from the `progression_engine` flag (F11.5): `v1` (default) or `v2`,
  the demo-only faulty engine of scenario S2 (it raises on bodyweight exercises). Any other value
  (including a stored unknown one) runs `v1`.
* Accepting stores the accepted (or edited) values as a new plan version (F8.2), so finished
  and in-progress sessions keep the targets they were performed against (rule 7, F8.1) and
  untouched sessions from today on use the new ones.
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

from app.engines import progression, progression_v2
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
from app.services import adaptive_calories, athlete, body, portion_rescale
from app.services.clock import local_today
from app.services.plans import NewPlannedExercise, NewTrainingDay, create_plan_version
from app.telemetry.metrics import SuggestionRule

Engine = Callable[[ProgressionInput], progression.Suggestion]
ENGINES: dict[str, Engine] = {"v1": progression.suggest, "v2": progression_v2.suggest}
DEFAULT_ENGINE = "v1"

_TARGET_KEYS = ("target_weight_kg", "reps_min", "reps_max", "target_seconds")


def engine_for(version: str) -> Engine:
    """The engine for a `progression_engine` flag value; unknown versions run v1."""
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
    db: Session,
    athlete_id: uuid.UUID,
    status: str,
    kind: str | None,
    now: dt.datetime,
) -> out.SuggestionList:
    query = select(Row).where(Row.athlete_id == athlete_id, Row.status == status)
    if kind is not None:
        query = query.where(Row.kind == kind)
    rows = db.scalars(query.order_by(Row.created_at.desc(), Row.id.desc()))
    owner = db.get(User, athlete_id)
    weigh_in_hint = adaptive_calories.hint(db, owner, now) if owner is not None else None
    return out.SuggestionList(items=[view(db, r) for r in rows], weigh_in_hint=weigh_in_hint)


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


def _accept_calories(
    db: Session,
    user: User,
    row: Row,
    overrides: out.SuggestionOverrides | None,
    now: dt.datetime,
) -> int:
    """Store the accepted kcal (proposed, or the edit-then-accept override) as the targets from
    today and rescale meal portions from today on (F14.4, D74). Returns the applied kcal."""
    given = set() if overrides is None else overrides.model_fields_set
    if given - {"kcal"}:
        raise _invalid("These overrides do not match the kind of this suggestion.")
    today = local_today(now, user.timezone)
    current = athlete.targets_on(db, user.id, today)
    if current is None:
        raise ProblemError(404, "not_onboarded", "There is no plan yet. Complete onboarding.")
    kcal = int(overrides.kcal) if overrides is not None and overrides.kcal is not None else None
    if kcal is not None and kcal < current.floor_kcal:
        raise _invalid(f"kcal must not be below the calorie floor of {current.floor_kcal}.")
    applied = (
        kcal if kcal is not None else max(int(row.payload["proposed_kcal"]), current.floor_kcal)
    )
    athlete.store_kcal(db, user.id, today, applied, now)
    portion_rescale.rescale_future_meals(
        db, athlete=user, author=user, new_kcal=applied, now=now, reason="calories"
    )
    return applied


def _active_plan(db: Session, athlete_id: uuid.UUID) -> Plan | None:
    return db.scalar(select(Plan).where(Plan.athlete_id == athlete_id, Plan.active.is_(True)))


def _target_in_plan(db: Session, row: Row, plan: Plan) -> PlannedExercise | None:
    """The planned exercise of the active `plan` that the suggestion targets: its own row if that
    row is in `plan`, else the same exercise on the same weekday (the plan was replaced since)."""
    planned = db.get(PlannedExercise, row.planned_exercise_id) if row.planned_exercise_id else None
    if planned is None:
        return None
    day = db.get(TrainingDay, planned.training_day_id)
    assert day is not None  # noqa: S101 - FK guarantees it
    if day.plan_id == plan.id:
        return planned
    return db.scalar(
        select(PlannedExercise)
        .join(TrainingDay, TrainingDay.id == PlannedExercise.training_day_id)
        .where(
            TrainingDay.plan_id == plan.id,
            TrainingDay.weekday == day.weekday,
            PlannedExercise.exercise_id == planned.exercise_id,
        )
        .order_by(PlannedExercise.position)
        .limit(1)
    )


def _apply_to_plan(
    db: Session, user: User, row: Row, applied: dict[str, Any], now: dt.datetime
) -> None:
    """Write the accepted targets as a new plan version (F8.2), like any other plan edit.

    Finished and in-progress sessions stay on the version they were performed against, so their
    targets and completion never change (rule 7, F8.1). Sessions that are still untouched from
    today on move to the new version, so they use the accepted targets. Pending suggestions
    follow their planned exercise to the new version."""
    old = _active_plan(db, row.athlete_id)
    target = None if old is None else _target_in_plan(db, row, old)
    if old is None or target is None:
        return
    timed = row.payload["exercise"]["type"] == "timed"
    days: list[NewTrainingDay] = []
    for day in old.training_days:
        items: list[NewPlannedExercise] = []
        for p in day.exercises:
            hit = p.id == target.id
            items.append(
                NewPlannedExercise(
                    exercise_id=p.exercise_id,
                    sets=p.sets,
                    rest_seconds=p.rest_seconds,
                    rule=p.rule,
                    increment_kg=p.increment_kg,
                    reps_min=applied["reps_min"] if hit and not timed else p.reps_min,
                    reps_max=applied["reps_max"] if hit and not timed else p.reps_max,
                    target_weight_kg=(
                        applied["target_weight_kg"] if hit and not timed else p.target_weight_kg
                    ),
                    target_seconds=applied["target_seconds"] if hit and timed else p.target_seconds,
                    deload_enabled=p.deload_enabled,
                    planned_kcal=p.planned_kcal,
                )
            )
        days.append(NewTrainingDay(day.weekday, day.name, items, day.planned_kcal, day.edited_by))
    old_days = list(old.training_days)
    # created_at is kept so the template still applies from the same first day (calendar).
    new = create_plan_version(
        db,
        athlete_id=row.athlete_id,
        author_id=user.id,
        source=old.source,
        days=days,
        now=old.created_at,
        revision=old.revision + 1,
    )
    new.updated_at = now
    db.add(
        PlanChange(
            plan_id=new.id,
            author_id=user.id,
            author_role=user.role,
            change={"kind": "suggestion_accepted", "suggestion_id": str(row.id)},
            created_at=now,
        )
    )
    day_map = {o.id: n for o, n in zip(old_days, new.training_days, strict=True)}
    planned_map: dict[uuid.UUID, uuid.UUID] = {}
    for o, n in zip(old_days, new.training_days, strict=True):
        for op, np_ in zip(o.exercises, n.exercises, strict=True):
            planned_map[op.id] = np_.id
    today = local_today(now, user.timezone)
    untouched = select(SetLog.session_id).where(SetLog.session_id == TrainingSession.id)
    for session in db.scalars(
        select(TrainingSession).where(
            TrainingSession.athlete_id == row.athlete_id,
            TrainingSession.plan_id == old.id,
            TrainingSession.status == "planned",
            TrainingSession.date >= today,
            ~untouched.exists(),
        )
    ):
        session.plan_id = new.id
        session.training_day_id = day_map[session.training_day_id].id
    for pending in db.scalars(
        select(Row).where(
            Row.athlete_id == row.athlete_id,
            Row.kind == "progression",
            Row.status == "pending",
            Row.planned_exercise_id.in_(list(planned_map)),
        )
    ):
        assert pending.planned_exercise_id is not None  # noqa: S101 - filtered above
        pending.planned_exercise_id = planned_map[pending.planned_exercise_id]
        pending.payload = {
            **pending.payload,
            "planned_exercise_id": str(pending.planned_exercise_id),
        }


def accept(
    db: Session,
    user: User,
    suggestion_id: uuid.UUID,
    overrides: out.SuggestionOverrides | None,
    now: dt.datetime,
) -> Row:
    row = _locked(db, user, suggestion_id)
    if row.kind == "recalc":
        if overrides is not None:
            raise _invalid("These overrides do not match the kind of this suggestion.")
        body.accept_recalc(db, user, row, now)
        row.status = "accepted"
        row.decided_by = user.id
        row.decided_at = now
        db.commit()
        return row
    if row.kind == "calories":
        row.payload = {
            **row.payload,
            "applied_kcal": _accept_calories(db, user, row, overrides, now),
        }
        row.status = "accepted"
        row.decided_by = user.id
        row.decided_at = now
        db.commit()
        return row
    applied = _applied(row, overrides)
    _apply_to_plan(db, user, row, applied, now)
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
