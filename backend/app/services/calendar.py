"""Calendar: sessions materialised from the active plan's weekly template (spec F9).

* The template repeats weekly; a `TrainingSession` row appears the first time a planned day is
  viewed (or logged). Until then a planned day is "virtual": the calendar derives it from the
  template, so ranges never write.
* "Today", "past" and `missed` are decided on the athlete's local calendar day (F9.1, F9.3).
* A moved session keeps `original_date`; the template day it left behind is a rest day.
* The template is never modified by a move (F9.2).

Nothing here logs: dates, plan names and training status are health data (spec §6.5).
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.engines.constants import DEFAULT_REST_SECONDS
from app.errors import ProblemError
from app.models import (
    Exercise,
    Plan,
    PlannedExercise,
    SetLog,
    TrainingDay,
    TrainingSession,
    User,
)
from app.models.plan import WEEKDAYS
from app.schemas import calendar as out
from app.services import suggestions
from app.services.clock import local_today
from app.services.plans import CALIBRATION_HINT, resolve_athlete

MAX_RANGE_DAYS = 42


def athlete_scope(user: User, athlete_id: str) -> uuid.UUID:
    """The athlete whose calendar is requested. Only athletes have one (coach access: #47)."""
    resolved = resolve_athlete(user, athlete_id)
    if user.role != "athlete":
        raise ProblemError(403, "not_linked", "You do not have access to this athlete.")
    return resolved


def weekday_of(day: dt.date) -> str:
    return WEEKDAYS[day.weekday()]


def utc_midnight_after(day: dt.date, timezone: str) -> dt.datetime:
    """Start of the day after `day` in `timezone`, as a UTC instant."""
    start = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, ZoneInfo(timezone))
    return start.astimezone(dt.UTC)


@dataclass
class _Template:
    plan: Plan | None
    start: dt.date  # first local day the template applies to
    by_weekday: dict[str, TrainingDay]


def _template(db: Session, user: User) -> _Template:
    plan = db.scalar(
        select(Plan)
        .where(Plan.athlete_id == user.id, Plan.active.is_(True))
        .options(selectinload(Plan.training_days))
    )
    if plan is None:
        return _Template(None, dt.date.max, {})
    by_weekday: dict[str, TrainingDay] = {}
    for day in plan.training_days:  # ordered by position: the first day of a weekday wins
        by_weekday.setdefault(day.weekday, day)
    # The template applies from the athlete's first plan: later versions (edits, regeneration)
    # change what is planned, not the day the calendar starts (D75).
    first = db.scalar(select(func.min(Plan.created_at)).where(Plan.athlete_id == user.id))
    start = (first or plan.created_at).astimezone(ZoneInfo(user.timezone)).date()
    return _Template(plan, start, by_weekday)


def _status(row_status: str, day: dt.date, today: dt.date) -> str:
    return "missed" if row_status == "planned" and day < today else row_status


# ───────────── day ─────────────


def resolve_date(value: str, user: User, now: dt.datetime) -> dt.date:
    if value == "today":
        return local_today(now, user.timezone)
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ProblemError(400, "bad_request", "The date is invalid.") from None


def _moved_away(db: Session, athlete_id: uuid.UUID, day: dt.date) -> bool:
    return (
        db.scalar(
            select(TrainingSession.id).where(
                TrainingSession.athlete_id == athlete_id,
                TrainingSession.original_date == day,
                TrainingSession.date != day,
            )
        )
        is not None
    )


def _get_row(db: Session, athlete_id: uuid.UUID, day: dt.date) -> TrainingSession | None:
    return db.scalar(
        select(TrainingSession).where(
            TrainingSession.athlete_id == athlete_id, TrainingSession.date == day
        )
    )


def _materialise(
    db: Session, user: User, tpl: _Template, day: dt.date, now: dt.datetime
) -> TrainingSession | None:
    """The session on `day`, creating it from the template when planned. Idempotent and safe
    under concurrent calls (the unique (athlete, date) constraint + ON CONFLICT DO NOTHING)."""
    row = _get_row(db, user.id, day)
    if row is not None:
        return row
    training_day = tpl.by_weekday.get(weekday_of(day))
    if tpl.plan is None or training_day is None or day < tpl.start:
        return None
    if _moved_away(db, user.id, day):
        return None
    db.execute(
        insert(TrainingSession)
        .values(
            id=uuid.uuid4(),
            athlete_id=user.id,
            plan_id=tpl.plan.id,
            training_day_id=training_day.id,
            date=day,
            status="planned",
            created_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_session_athlete_id_date")
    )
    db.commit()
    return _get_row(db, user.id, day)


def get_day(db: Session, user: User, date_text: str, now: dt.datetime) -> out.DayView:
    from app.services import meal_log, training_log

    day = resolve_date(date_text, user, now)
    today = local_today(now, user.timezone)
    tpl = _template(db, user)
    row = _materialise(db, user, tpl, day, now)
    view = session_view(db, user, row, today) if row else None
    status = "rest" if view is None else view.status
    nutrition = meal_log.day_nutrition(db, user, day)
    meal_day, _ = meal_log.planned_meals(db, user, day)
    return out.DayView(
        date=day,
        weekday=weekday_of(day),  # type: ignore[arg-type]
        is_today=day == today,
        training_status=status,
        session=view,
        meals=[{"planned_meal": planned, "log": log} for planned, log in nutrition.meals],
        extra_meal_logs=nutrition.extra_logs,
        activities=training_log.day_activities(db, user, day),
        energy=training_log.day_energy(db, user, day, nutrition),
        training_completion=view.completion if view else None,
        nutrition_completion=nutrition.completion,
        pending_suggestions=[],
        notes=[],
        meal_warning=meal_day.warning if meal_day else None,
    )


# ───────────── range ─────────────


@dataclass(frozen=True)
class TrainingDayInfo:
    """One local day of the training calendar: derived status and the session's stored values."""

    date: dt.date
    status: str
    session_id: uuid.UUID | None
    name: str | None
    completion: float | None
    moved: bool


def training_days(
    db: Session, user: User, start: dt.date, end: dt.date, today: dt.date
) -> list[TrainingDayInfo]:
    """Status of every day in `start..end` from the stored sessions and the weekly template, in
    a fixed number of queries and without writing (planned days stay virtual)."""
    tpl = _template(db, user)
    rows = db.execute(
        select(TrainingSession, TrainingDay.name)
        .join(TrainingDay, TrainingDay.id == TrainingSession.training_day_id)
        .where(
            TrainingSession.athlete_id == user.id,
            or_(
                TrainingSession.date.between(start, end),
                TrainingSession.original_date.between(start, end),
            ),
        )
    ).all()
    on_date = {r.date: (r, name) for r, name in rows}
    left_behind = {
        r.original_date for r, _ in rows if r.original_date and r.original_date != r.date
    }
    result: list[TrainingDayInfo] = []
    for offset in range((end - start).days + 1):
        day = start + dt.timedelta(days=offset)
        session_id: uuid.UUID | None = None
        name: str | None = None
        status = "rest"
        completion: float | None = None
        moved = False
        if day in on_date:
            row, name = on_date[day]
            session_id, status = row.id, _status(row.status, day, today)
            completion, moved = row.completion, row.original_date is not None
        elif (
            tpl.plan is not None
            and day >= tpl.start
            and day not in left_behind
            and (template_day := tpl.by_weekday.get(weekday_of(day)))
        ):
            name = template_day.name
            status = "missed" if day < today else "planned"
        result.append(TrainingDayInfo(day, status, session_id, name, completion, moved))
    return result


def get_calendar(
    db: Session, user: User, start: dt.date, end: dt.date, now: dt.datetime
) -> out.CalendarRange:
    if start > end:
        raise ProblemError(400, "invalid_range", "`from` must not be after `to`.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ProblemError(
            400, "range_too_large", f"The range may cover at most {MAX_RANGE_DAYS} days."
        )
    from app.services import training_log

    today = local_today(now, user.timezone)
    plan_days = training_days(db, user, start, end, today)
    energy = training_log.range_energy(db, user, start, end)
    days: list[out.CalendarDay] = [
        out.CalendarDay(
            date=info.date,
            weekday=weekday_of(info.date),  # type: ignore[arg-type]
            is_today=info.date == today,
            training_status=info.status,  # type: ignore[arg-type]
            session_id=info.session_id,
            training_day_name=info.name,
            moved=info.moved,
            training_completion=info.completion,
            energy=energy[info.date],
        )
        for info in plan_days
    ]
    return out.CalendarRange(from_=start, to=end, timezone=user.timezone, days=days)


# ───────────── session ─────────────


def session_view(db: Session, user: User, row: TrainingSession, today: dt.date) -> out.Session:
    from app.services import training_log  # imported late: training_log builds on this module

    training_day, exercises = training_log.load_day(db, row)
    plan = db.get(Plan, row.plan_id)
    assert plan is not None  # noqa: S101 - FK guarantees it
    logs = list(db.scalars(select(SetLog).where(SetLog.session_id == row.id)))
    _, per_exercise = training_log.session_completion(training_day, exercises, logs)
    logs_by_exercise: dict[uuid.UUID, dict[int, SetLog]] = {}
    for log in sorted(logs, key=lambda x: (x.logged_at, x.set_no)):
        logs_by_exercise.setdefault(log.exercise_id, {})[log.set_no] = log

    pending = suggestions.pending_by_planned_exercise(
        db, row.athlete_id, [p.id for p in training_day.exercises]
    )

    def summary(exercise: Exercise) -> dict[str, Any]:
        return {
            "id": exercise.id,
            "name": exercise.name,
            "type": exercise.type,
            "equipment": exercise.equipment,
            "muscle_group": exercise.muscle_group,
        }

    def set_item(n: int, extra: bool, log: SetLog | None, planned: PlannedExercise | None) -> Any:
        if log is not None:  # logged sets show the snapshot they were performed against
            targets = (log.target_reps, log.target_weight_kg, log.target_seconds)
        elif planned is not None:
            targets = (planned.reps_min, planned.target_weight_kg, planned.target_seconds)
        else:
            targets = (None, None, None)
        return {
            "set_no": n,
            "is_extra": extra,
            "target_reps": targets[0],
            "target_weight_kg": targets[1],
            "target_seconds": targets[2],
            "log": log,
        }

    items: list[out.SessionExercise] = []
    planned_exercise_ids: set[uuid.UUID] = set()
    for planned in training_day.exercises:
        exercise = exercises[planned.exercise_id]
        planned_exercise_ids.add(planned.exercise_id)
        done = logs_by_exercise.get(planned.exercise_id, {})
        sets = [set_item(n, False, done.get(n), planned) for n in range(1, planned.sets + 1)]
        sets += [
            set_item(n, True, log, planned) for n, log in sorted(done.items()) if n > planned.sets
        ]
        items.append(
            out.SessionExercise.model_validate(
                {
                    "planned_exercise_id": planned.id,
                    "exercise": summary(exercise),
                    "order": planned.position,
                    "is_extra": False,
                    "rule": planned.rule,
                    "sets": sets,
                    "reps_min": planned.reps_min,
                    "reps_max": planned.reps_max,
                    "rest_seconds": planned.rest_seconds,
                    "calibration_hint": (
                        CALIBRATION_HINT
                        if planned.target_weight_kg is None and exercise.type != "timed"
                        else None
                    ),
                    "completion": per_exercise[planned.id].ratio if done else None,
                    "pending_suggestion_id": pending.get(planned.id),
                },
                from_attributes=True,
            )
        )
    extra_order = max((p.position for p in training_day.exercises), default=0)
    for exercise_id, done in logs_by_exercise.items():
        if exercise_id in planned_exercise_ids:
            continue
        extra_order += 1
        items.append(
            out.SessionExercise.model_validate(
                {
                    "planned_exercise_id": None,
                    "exercise": summary(exercises[exercise_id]),
                    "order": extra_order,
                    "is_extra": True,
                    "rule": None,
                    "sets": [set_item(n, True, log, None) for n, log in sorted(done.items())],
                    "reps_min": None,
                    "reps_max": None,
                    "rest_seconds": DEFAULT_REST_SECONDS,
                    "calibration_hint": None,
                    "completion": None,
                    "pending_suggestion_id": None,
                },
                from_attributes=True,
            )
        )
    return out.Session.model_validate(
        {
            "id": row.id,
            "athlete_id": row.athlete_id,
            "plan_id": row.plan_id,
            "plan_version": plan.version,
            "training_day_id": row.training_day_id,
            "training_day_name": training_day.name,
            "date": row.date,
            "original_date": row.original_date,
            "status": _status(row.status, row.date, today),
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "editable_until": utc_midnight_after(row.date + dt.timedelta(days=1), user.timezone),
            "completion": row.completion,
            "kcal": row.kcal,
            "exercises": items,
        },
        from_attributes=True,
    )


def owned_session(db: Session, user: User, session_id: uuid.UUID) -> TrainingSession:
    """403 for an unknown id and for another athlete's session alike (D41: no id enumeration)."""
    row = db.get(TrainingSession, session_id)
    if row is None or row.athlete_id != user.id:
        raise ProblemError(403, "not_linked", "You do not have access to this athlete.")
    return row


def get_session(db: Session, user: User, session_id: uuid.UUID, now: dt.datetime) -> out.Session:
    row = owned_session(db, user, session_id)
    return session_view(db, user, row, local_today(now, user.timezone))


def _iso_week(day: dt.date) -> tuple[int, int]:
    iso = day.isocalendar()
    return iso.year, iso.week


def move_session(
    db: Session, user: User, session_id: uuid.UUID, target: dt.date, now: dt.datetime
) -> out.Session:
    """D45: not finished, same ISO week (Monday start), today or later, target day free."""
    row = owned_session(db, user, session_id)
    if user.role != "athlete":
        raise ProblemError(403, "wrong_role", "Only the athlete can move sessions.")
    today = local_today(now, user.timezone)
    if row.status == "done" or row.finished_at is not None:
        raise ProblemError(409, "session_finished", "A finished session cannot be moved.")
    if _iso_week(target) != _iso_week(row.date):
        raise ProblemError(409, "outside_week", "A session can only move within its week.")
    if target < today:
        raise ProblemError(409, "date_in_past", "A session cannot move to a day in the past.")
    tpl = _template(db, user)
    occupied = _get_row(db, user.id, target) is not None or (
        tpl.plan is not None
        and target >= tpl.start
        and weekday_of(target) in tpl.by_weekday
        and not _moved_away(db, user.id, target)
    )
    if occupied:
        raise ProblemError(409, "day_occupied", "That day already has a session.")
    original = row.original_date or row.date
    row.date = target
    row.original_date = None if target == original else original
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ProblemError(409, "day_occupied", "That day already has a session.") from None
    return session_view(db, user, row, today)
