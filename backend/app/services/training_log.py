"""Training logging (spec F10): sets, finishing a workout, extra activities, day energy.

* A set log is unique per (session, exercise, set number); logging again replaces it (F10.1).
  The first log snapshots the planned targets onto the row and later plan edits never touch it
  (CLAUDE.md rule 7).
* Completion (F10.2) and session kcal (F13.2) come from the pure engines. Session kcal uses the
  most recent body weight on or before the session date, so a later weigh-in never changes it.
* A finished session can be edited until `editable_until` (the end of the day after the session
  date in the athlete's time zone); later edits are `409 edit_window_closed` (F10.3). Editing a
  finished session recomputes completion and kcal.
* Mutations lock the session row, so concurrent retries serialise instead of racing.

Nothing here logs: reps, weights and activities are health data (spec section 6.5).
"""

import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.engines import energy_balance as energy_engine
from app.engines.constants import DEFAULT_REST_SECONDS
from app.engines.exercise_kcal import ExtraActivity as EngineActivity
from app.engines.exercise_kcal import LoggedExercise, logged_kcal
from app.engines.session_completion import Completion, PlannedSetResult, completion
from app.errors import ProblemError
from app.models import (
    BodyMetric,
    Exercise,
    ExtraActivity,
    PlannedExercise,
    SetLog,
    Targets,
    TrainingDay,
    TrainingSession,
    User,
)
from app.schemas import calendar as cal
from app.schemas import logging as out
from app.schemas.plans import ExerciseSummary
from app.services import meal_log
from app.services.athlete import targets_on
from app.services.calendar import session_of, utc_midnight_after


def editable_until(row: TrainingSession, user: User) -> dt.datetime:
    return utc_midnight_after(row.date + dt.timedelta(days=1), user.timezone)


def body_weight(db: Session, athlete_id: uuid.UUID, day: dt.date) -> float | None:
    """Most recent weight on or before `day`; for days before the first weigh-in, the earliest."""
    base = select(BodyMetric.weight_kg).where(
        BodyMetric.user_id == athlete_id, BodyMetric.weight_kg.is_not(None)
    )
    weight = db.scalar(base.where(BodyMetric.date <= day).order_by(BodyMetric.date.desc()).limit(1))
    if weight is None:
        weight = db.scalar(base.order_by(BodyMetric.date.asc()).limit(1))
    return weight


def _visible_exercise(db: Session, user: User, exercise_id: uuid.UUID) -> Exercise:
    exercise = db.get(Exercise, exercise_id)
    if exercise is None or exercise.owner_id not in (None, user.id):
        raise ProblemError(404, "exercise_not_found", "That exercise does not exist.")
    return exercise


# ───────────── completion and kcal ─────────────


def planned_results(
    planned: PlannedExercise, exercise: Exercise, logs: Sequence[SetLog]
) -> list[PlannedSetResult]:
    """The planned working sets of one planned exercise, with what was done (F10.2).

    Logged sets use their target snapshot, never the live plan; unlogged ones use the plan."""
    by_no = {log.set_no: log for log in logs if log.exercise_id == planned.exercise_id}
    timed = exercise.type == "timed"
    results: list[PlannedSetResult] = []
    for n in range(1, planned.sets + 1):
        log = by_no.get(n)
        if log is None:
            results.append(PlannedSetResult(planned.target_seconds if timed else planned.reps_min))
            continue
        target = log.target_seconds if timed else log.target_reps
        actual = None if log.skipped else (log.seconds if timed else log.reps)
        results.append(PlannedSetResult(target, actual))
    return results


def session_completion(
    training_day: TrainingDay, exercises: dict[uuid.UUID, Exercise], logs: Sequence[SetLog]
) -> tuple[Completion, dict[uuid.UUID, Completion]]:
    """Overall completion and per planned exercise (keyed by the planned exercise id)."""
    all_sets: list[PlannedSetResult] = []
    per_exercise: dict[uuid.UUID, Completion] = {}
    for planned in training_day.exercises:
        sets = planned_results(planned, exercises[planned.exercise_id], logs)
        per_exercise[planned.id] = completion(sets)
        all_sets.extend(sets)
    return completion(all_sets), per_exercise


def load_day(db: Session, row: TrainingSession) -> tuple[TrainingDay, dict[uuid.UUID, Exercise]]:
    """The session's training day and every exercise it or its set logs refer to."""
    training_day = db.scalar(
        select(TrainingDay)
        .where(TrainingDay.id == row.training_day_id)
        .options(selectinload(TrainingDay.exercises))
    )
    assert training_day is not None  # noqa: S101 - FK guarantees it
    ids = {p.exercise_id for p in training_day.exercises}
    ids |= set(db.scalars(select(SetLog.exercise_id).where(SetLog.session_id == row.id)))
    exercises = {e.id: e for e in db.scalars(select(Exercise).where(Exercise.id.in_(ids)))}
    return training_day, exercises


def session_kcal(
    training_day: TrainingDay,
    exercises: dict[uuid.UUID, Exercise],
    logs: Sequence[SetLog],
    weight_kg: float,
) -> int:
    """F13.2 kcal of the performed sets (extra sets and exercises included)."""
    rest = {p.exercise_id: p.rest_seconds for p in training_day.exercises}
    grouped: dict[uuid.UUID, list[SetLog]] = defaultdict(list)
    for log in logs:
        if not log.skipped:
            grouped[log.exercise_id].append(log)
    parts: list[LoggedExercise] = []
    for exercise_id, items in grouped.items():
        exercise = exercises[exercise_id]
        if exercise.type == "timed":
            parts.append(
                LoggedExercise(
                    "timed", exercise.met, durations_seconds=[i.seconds or 0 for i in items]
                )
            )
        else:
            parts.append(
                LoggedExercise(
                    exercise.type,  # type: ignore[arg-type]
                    exercise.met,
                    performed_sets=len(items),
                    rest_seconds=rest.get(exercise_id, DEFAULT_REST_SECONDS),
                )
            )
    return logged_kcal(parts, weight_kg).kcal


def _recompute(db: Session, row: TrainingSession) -> None:
    """Refresh the stored completion, and kcal once the session is finished."""
    logs = list(db.scalars(select(SetLog).where(SetLog.session_id == row.id)))
    training_day, exercises = load_day(db, row)
    overall, _ = session_completion(training_day, exercises, logs)
    row.completion = overall.ratio if logs or row.status == "done" else None
    if row.status == "done":
        weight = body_weight(db, row.athlete_id, row.date)
        row.kcal = None if weight is None else session_kcal(training_day, exercises, logs, weight)


# ───────────── sessions ─────────────


def _locked_session(
    db: Session, user: User, session_id: uuid.UUID, now: dt.datetime
) -> TrainingSession:
    session_of(db, user, session_id)  # 403 for another athlete's or unknown ids
    row = db.scalar(
        select(TrainingSession)
        .where(TrainingSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None  # noqa: S101 - just found it
    if row.status == "done" and now >= editable_until(row, user):
        raise ProblemError(409, "edit_window_closed", "This session can no longer be edited.")
    return row


def _invalid(detail: str) -> ProblemError:
    return ProblemError(422, "invalid_set", detail)


def _resolve_values(
    body: out.SetLogInput, exercise: Exercise, planned: PlannedExercise | None
) -> tuple[int | None, float | None, int | None, float | None]:
    """The (reps, weight, seconds, distance) to store for a set, validated by exercise type."""
    given = {
        name
        for name in ("reps", "weight_kg", "seconds", "distance_m")
        if getattr(body, name) is not None
    }
    timed = exercise.type == "timed"
    if body.as_planned and body.skipped:
        raise _invalid("A set cannot be both as_planned and skipped.")
    if body.skipped or body.as_planned:
        if given:
            raise _invalid("Send as_planned or skipped without reps, weight or duration.")
        if body.skipped:
            return None, None, None, None
        if planned is None:
            raise _invalid("An extra set has no planned targets.")
        if timed:
            if planned.target_seconds is None:
                raise _invalid("The planned set has no target to copy.")
            return None, None, planned.target_seconds, None
        if planned.reps_min is None:
            raise _invalid("The planned set has no target to copy.")
        return planned.reps_min, planned.target_weight_kg, None, None
    allowed = {"seconds", "distance_m"} if timed else {"reps", "weight_kg"}
    if not given <= allowed:
        raise _invalid(f"A {exercise.type} exercise does not accept {sorted(given - allowed)}.")
    needed = (
        {"seconds"}
        if timed
        else ({"reps", "weight_kg"} if exercise.type == "strength" else {"reps"})
    )
    if not needed <= given:
        raise _invalid(f"Send {sorted(needed)}, or as_planned, or skipped.")
    return body.reps, body.weight_kg, body.seconds, body.distance_m


def log_set(
    db: Session, user: User, session_id: uuid.UUID, body: out.SetLogInput, now: dt.datetime
) -> tuple[SetLog, bool]:
    """Upsert one set. Returns the log and whether it was created (F10.1)."""
    row = _locked_session(db, user, session_id, now)
    exercise = _visible_exercise(db, user, body.exercise_id)
    training_day, _ = load_day(db, row)
    candidates = [p for p in training_day.exercises if p.exercise_id == body.exercise_id]
    planned: PlannedExercise | None
    if body.planned_exercise_id is not None:
        planned = next((p for p in candidates if p.id == body.planned_exercise_id), None)
        if planned is None:
            raise ProblemError(
                422,
                "planned_exercise_mismatch",
                "planned_exercise_id is not this exercise in the session's plan.",
            )
    else:
        planned = candidates[0] if candidates else None
    reps, weight, seconds, distance = _resolve_values(body, exercise, planned)

    log = db.scalar(
        select(SetLog).where(
            SetLog.session_id == row.id,
            SetLog.exercise_id == body.exercise_id,
            SetLog.set_no == body.set_no,
        )
    )
    created = log is None
    if log is None:
        # The first log fixes the target snapshot; replacing a set never rewrites it.
        log = SetLog(
            session_id=row.id,
            exercise_id=body.exercise_id,
            set_no=body.set_no,
            planned_exercise_id=planned.id if planned else None,
            target_reps=planned.reps_min if planned else None,
            target_weight_kg=planned.target_weight_kg if planned else None,
            target_seconds=planned.target_seconds if planned else None,
        )
        db.add(log)
    log.skipped = body.skipped
    log.reps, log.weight_kg, log.seconds, log.distance_m = reps, weight, seconds, distance
    log.logged_at = now
    if row.status == "planned":
        row.status = "in_progress"
        row.started_at = now
    db.flush()
    _recompute(db, row)
    db.commit()
    return log, created


def delete_set(
    db: Session, user: User, session_id: uuid.UUID, set_log_id: uuid.UUID, now: dt.datetime
) -> None:
    row = _locked_session(db, user, session_id, now)
    log = db.get(SetLog, set_log_id)
    if log is None or log.session_id != row.id:
        raise ProblemError(404, "set_log_not_found", "That set log does not exist.")
    db.delete(log)
    db.flush()
    _recompute(db, row)
    db.commit()


def finish_session(
    db: Session,
    user: User,
    session_id: uuid.UUID,
    finished_at: dt.datetime | None,
    now: dt.datetime,
) -> tuple[TrainingSession, bool]:
    """Close the session. Returns it and whether this call finished it (not a re-finish)."""
    row = _locked_session(db, user, session_id, now)
    when = finished_at or now
    if when.tzinfo is None:
        raise ProblemError(422, "invalid_finished_at", "finished_at needs a time zone offset.")
    if when > now + dt.timedelta(minutes=1):
        raise ProblemError(422, "invalid_finished_at", "finished_at cannot be in the future.")
    started = row.started_at or when
    if when < started:
        raise ProblemError(422, "invalid_finished_at", "finished_at is before the session started.")
    first = row.status != "done"
    row.status = "done"
    row.started_at = started
    row.finished_at = when
    db.flush()
    _recompute(db, row)
    db.commit()
    return row, first


# ───────────── extra activities and day energy ─────────────


def _activity_view(activity: ExtraActivity, exercise: Exercise) -> out.Activity:
    return out.Activity(
        id=activity.id,
        date=activity.date,
        exercise=ExerciseSummary(
            id=exercise.id,
            name=exercise.name,
            type=exercise.type,  # type: ignore[arg-type]
            equipment=exercise.equipment,  # type: ignore[arg-type]
            muscle_group=exercise.muscle_group,  # type: ignore[arg-type]
        ),
        minutes=activity.minutes,
        kcal=activity.kcal,
        created_at=activity.created_at,
    )


def day_activities(db: Session, user: User, day: dt.date) -> list[out.Activity]:
    rows = db.execute(
        select(ExtraActivity, Exercise)
        .join(Exercise, Exercise.id == ExtraActivity.exercise_id)
        .where(ExtraActivity.athlete_id == user.id, ExtraActivity.date == day)
        .order_by(ExtraActivity.created_at, ExtraActivity.id)
    ).all()
    return [_activity_view(a, e) for a, e in rows]


def _energy(
    day: dt.date,
    eaten: cal.Macros,
    planned: cal.Macros,
    training: int,
    activities: int,
    row: Targets | None,
) -> cal.EnergyBalance:
    """One day's balance from its parts and the `Targets` row valid on it (F13.1, F13.3)."""
    baseline = row.baseline_kcal if row else 0
    result = energy_engine.day_balance(
        energy_engine.EnergyInputs(eaten.kcal, baseline, training, activities)
    )
    target = (
        cal.Macros(kcal=row.kcal, protein_g=row.protein_g, carbs_g=row.carbs_g, fat_g=row.fat_g)
        if row
        else cal.Macros()
    )
    return cal.EnergyBalance(
        date=day,
        eaten=eaten,
        planned=planned,
        target=target,
        burned=cal.Burned(
            total_kcal=result.burned_kcal,
            baseline_kcal=baseline,
            training_kcal=training,
            activities_kcal=activities,
        ),
        balance_kcal=result.balance_kcal,
        target_balance_kcal=row.target_balance_kcal if row else 0,
    )


def day_energy(
    db: Session,
    user: User,
    day: dt.date,
    nutrition: "meal_log.DayNutrition | None" = None,
) -> cal.EnergyBalance:
    """Eaten (F12.1, logged quantities only), planned, burned (F13.1) and target kcal for `day`.

    The baseline, targets and target balance come from the `Targets` row valid on `day`
    (latest `valid_from <= day`, the first row for earlier days), so later target changes never
    alter a past day (F13.2). An athlete without targets gets a zero baseline."""
    nutrition = nutrition or meal_log.day_nutrition(db, user, day)
    training = db.scalar(
        select(func.coalesce(func.sum(TrainingSession.kcal), 0)).where(
            TrainingSession.athlete_id == user.id,
            TrainingSession.date == day,
            TrainingSession.status == "done",
        )
    )
    activities = db.scalar(
        select(func.coalesce(func.sum(ExtraActivity.kcal), 0)).where(
            ExtraActivity.athlete_id == user.id, ExtraActivity.date == day
        )
    )
    row = targets_on(db, user.id, day)
    return _energy(
        day,
        nutrition.eaten,
        nutrition.planned_totals,
        int(training or 0),
        int(activities or 0),
        row,
    )


def range_energy(
    db: Session, user: User, start: dt.date, end: dt.date
) -> dict[dt.date, cal.EnergyBalance]:
    """`day_energy` for every day in `start..end` in a fixed number of queries (week/month)."""
    totals = meal_log.range_totals(db, user, start, end)
    training = dict(
        db.execute(
            select(TrainingSession.date, func.coalesce(func.sum(TrainingSession.kcal), 0))
            .where(
                TrainingSession.athlete_id == user.id,
                TrainingSession.date.between(start, end),
                TrainingSession.status == "done",
            )
            .group_by(TrainingSession.date)
        ).all()
    )
    activities = dict(
        db.execute(
            select(ExtraActivity.date, func.coalesce(func.sum(ExtraActivity.kcal), 0))
            .where(ExtraActivity.athlete_id == user.id, ExtraActivity.date.between(start, end))
            .group_by(ExtraActivity.date)
        ).all()
    )
    rows = list(db.scalars(select(Targets).where(Targets.user_id == user.id)))
    rows.sort(key=lambda r: r.valid_from)
    result: dict[dt.date, cal.EnergyBalance] = {}
    for offset in range((end - start).days + 1):
        day = start + dt.timedelta(days=offset)
        valid = [r for r in rows if r.valid_from <= day]
        row = valid[-1] if valid else (rows[0] if rows else None)
        eaten, planned = totals[day]
        result[day] = _energy(
            day, eaten, planned, int(training.get(day) or 0), int(activities.get(day) or 0), row
        )
    return result


def log_activity(
    db: Session, user: User, body: out.ActivityInput, now: dt.datetime
) -> out.ActivityResult:
    exercise = _visible_exercise(db, user, body.exercise_id)
    if exercise.type != "timed":
        raise ProblemError(
            422, "not_timed_exercise", "Extra activities must be timed/cardio exercises."
        )
    weight = body_weight(db, user.id, body.date)
    if weight is None:
        raise ProblemError(422, "no_body_weight", "Log a body weight before logging activities.")
    kcal = logged_kcal([], weight, [EngineActivity(met=exercise.met, minutes=body.minutes)]).kcal
    activity = ExtraActivity(
        athlete_id=user.id,
        date=body.date,
        exercise_id=exercise.id,
        minutes=body.minutes,
        kcal=kcal,
        created_at=now,
    )
    db.add(activity)
    db.commit()
    return out.ActivityResult(
        activity=_activity_view(activity, exercise), energy=day_energy(db, user, body.date)
    )


def delete_activity(db: Session, user: User, activity_id: uuid.UUID) -> out.DayEnergyUpdate:
    activity = db.get(ExtraActivity, activity_id)
    if activity is None or activity.athlete_id != user.id:
        raise ProblemError(404, "activity_not_found", "That activity does not exist.")
    day = activity.date
    db.delete(activity)
    db.commit()
    return out.DayEnergyUpdate(energy=day_energy(db, user, day))
