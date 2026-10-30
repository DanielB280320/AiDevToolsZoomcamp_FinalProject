"""Chart series (spec F15): pre-aggregated on the server so the browser never aggregates raw logs.

* Every series is built from a fixed number of queries for its range, so a year of data stays
  fast (p95 < 500 ms, F15.1; measured in `tests/integration/test_charts_perf.py`).
* Exercise history and the session detail use the target snapshots stored with each set log,
  never the current plan (F15.2, rule 7).
* Weights are returned in kg; the client converts to the user's display units at the edge
  (rule 5, F15.4).

Nothing here logs: every value is health data (spec section 6.5).
"""

import datetime as dt
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines import charts as engine
from app.engines.nutrition_completion import nutrition_completion
from app.errors import ProblemError
from app.models import (
    BodyMetric,
    MealDay,
    MealLog,
    Plan,
    PlannedMeal,
    SetLog,
    TrainingSession,
    User,
)
from app.models.plan import WEEKDAYS
from app.schemas import charts as out
from app.schemas.plans import ExerciseSummary
from app.services import athlete, calendar, training_log
from app.services.calendar import TrainingDayInfo, utc_midnight_after
from app.services.clock import local_today

WEEKS_CHOICES = (4, 12, 26, 52)
MAX_ADHERENCE_DAYS = 371
WEIGHT_DECIMALS = 2


def check_weeks(weeks: int) -> int:
    if weeks not in WEEKS_CHOICES:
        raise ProblemError(400, "bad_request", "`weeks` must be one of 4, 12, 26 or 52.")
    return weeks


def _range_start(today: dt.date, weeks: int) -> dt.date:
    return today - dt.timedelta(days=weeks * 7 - 1)


# ───────────── session detail ─────────────


def session_chart(
    db: Session, user: User, session_id: uuid.UUID, now: dt.datetime
) -> out.SessionChart:
    row = calendar.owned_session(db, user, session_id)
    view = calendar.session_view(db, user, row, local_today(now, user.timezone))
    exercises: list[out.SessionChartExercise] = []
    for item in view.exercises:
        timed = item.exercise.type == "timed"
        sets: list[out.SessionChartSet] = []
        for s in item.sets:
            log = s.log
            outcome = engine.set_outcome(
                engine.SetValues(
                    s.target_reps,
                    s.target_weight_kg,
                    s.target_seconds,
                    log.reps if log else None,
                    log.weight_kg if log else None,
                    log.seconds if log else None,
                ),
                logged=log is not None,
                skipped=bool(log and log.skipped),
                extra=s.is_extra,
                timed=timed,
            )
            sets.append(
                out.SessionChartSet(
                    set_no=s.set_no,
                    status=outcome.status,
                    completion=outcome.completion,
                    target_reps=s.target_reps,
                    target_weight_kg=s.target_weight_kg,
                    target_seconds=s.target_seconds,
                    reps=log.reps if log else None,
                    weight_kg=log.weight_kg if log else None,
                    seconds=log.seconds if log else None,
                )
            )
        exercises.append(
            out.SessionChartExercise(
                exercise=item.exercise,
                is_extra=item.is_extra,
                completion=item.completion,
                sets=sets,
            )
        )
    return out.SessionChart(
        session_id=view.id,
        date=view.date,
        training_day_name=view.training_day_name,
        status=view.status,
        completion=view.completion,
        kcal=view.kcal,
        exercises=exercises,
    )


# ───────────── exercise over time ─────────────


def exercise_chart(
    db: Session, user: User, exercise_id: uuid.UUID, weeks: int, now: dt.datetime
) -> out.ExerciseChart:
    exercise = training_log._visible_exercise(db, user, exercise_id)
    today = local_today(now, user.timezone)
    start = _range_start(today, weeks)
    rows = db.execute(
        select(SetLog, TrainingSession.date)
        .join(TrainingSession, TrainingSession.id == SetLog.session_id)
        .where(
            TrainingSession.athlete_id == user.id,
            TrainingSession.status == "done",
            TrainingSession.date <= today,
            SetLog.exercise_id == exercise_id,
            SetLog.skipped.is_(False),
        )
    ).all()
    by_session: dict[uuid.UUID, tuple[dt.date, list[engine.LoggedSet]]] = {}
    for log, day in rows:  # full history, so a personal record accounts for earlier sessions
        by_session.setdefault(log.session_id, (day, []))[1].append(
            engine.LoggedSet(
                log.set_no,
                engine.SetValues(
                    log.target_reps,
                    log.target_weight_kg,
                    log.target_seconds,
                    log.reps,
                    log.weight_kg,
                    log.seconds,
                ),
            )
        )
    history = engine.exercise_history(
        ((str(sid), day, sets) for sid, (day, sets) in by_session.items()),
        timed=exercise.type == "timed",
    )
    points = [
        out.ExerciseChartPoint(
            date=p.date,
            session_id=uuid.UUID(p.session_id),
            target_weight_kg=p.target_weight_kg,
            target_reps=p.target_reps,
            target_seconds=p.target_seconds,
            top_set_weight_kg=p.top_set_weight_kg,
            top_set_reps=p.top_set_reps,
            top_set_seconds=p.top_set_seconds,
            volume_kg=p.volume_kg,
            is_pr=p.is_pr,
        )
        for p in history
        if p.date >= start
    ]
    return out.ExerciseChart(
        exercise=ExerciseSummary.model_validate(exercise, from_attributes=True),
        weeks=weeks,
        points=points,
    )


# ───────────── adherence ─────────────


def _training_completion(info: TrainingDayInfo, today: dt.date) -> float | None:
    """Rest, planned and future days have none; a missed session counts as 0 (nothing done)."""
    if info.status == "missed":
        return info.completion or 0.0
    if info.status in ("in_progress", "done") and info.date <= today:
        return info.completion
    return None


def _nutrition_completion(
    db: Session, user: User, start: dt.date, end: dt.date, today: dt.date
) -> dict[dt.date, float | None]:
    """F12.2 completion for each day up to today in three queries (plan version per day as in
    `meal_log.planned_meals`; logs matched by meal key, D73)."""
    last = min(end, today)
    result: dict[dt.date, float | None] = {}
    if last < start:
        return result
    versions = db.execute(
        select(MealDay.id, MealDay.weekday, Plan.created_at)
        .join(Plan, Plan.id == MealDay.plan_id)
        .where(Plan.athlete_id == user.id)
        .order_by(Plan.version.desc())
    ).all()
    by_weekday: dict[str, list[tuple[uuid.UUID, dt.datetime]]] = defaultdict(list)
    for meal_day_id, weekday, created_at in versions:
        by_weekday[weekday].append((meal_day_id, created_at))
    chosen: dict[dt.date, uuid.UUID] = {}
    for offset in range((last - start).days + 1):
        day = start + dt.timedelta(days=offset)
        cutoff = utc_midnight_after(day, user.timezone)
        for meal_day_id, created_at in by_weekday.get(WEEKDAYS[day.weekday()], []):
            if created_at < cutoff:
                chosen[day] = meal_day_id
                break
    meals: dict[uuid.UUID, list[uuid.UUID | None]] = defaultdict(list)
    if chosen:
        for meal_day_id, meal_key in db.execute(
            select(PlannedMeal.meal_day_id, PlannedMeal.meal_key).where(
                PlannedMeal.meal_day_id.in_(set(chosen.values()))
            )
        ):
            meals[meal_day_id].append(meal_key)
    status_by: dict[tuple[dt.date, uuid.UUID | None], str] = {}
    for day, key, status in db.execute(
        select(MealLog.date, MealLog.meal_key, MealLog.status).where(
            MealLog.athlete_id == user.id,
            MealLog.date.between(start, last),
            MealLog.planned_meal_id.is_not(None),
            MealLog.meal_key.is_not(None),
        )
    ):
        status_by[(day, key)] = status
    for offset in range((last - start).days + 1):
        day = start + dt.timedelta(days=offset)
        keys = meals[chosen[day]] if day in chosen else []
        statuses = [status_by.get((day, k)) if k is not None else None for k in keys]
        result[day] = nutrition_completion(statuses).ratio
    return result


def adherence_chart(
    db: Session, user: User, start: dt.date, end: dt.date, now: dt.datetime
) -> out.AdherenceChart:
    if start > end:
        raise ProblemError(400, "invalid_range", "`from` must not be after `to`.")
    if (end - start).days + 1 > MAX_ADHERENCE_DAYS:
        raise ProblemError(
            400, "range_too_large", f"The range may cover at most {MAX_ADHERENCE_DAYS} days."
        )
    today = local_today(now, user.timezone)
    infos = calendar.training_days(db, user, start, end, today)
    nutrition = _nutrition_completion(db, user, start, end, today)
    days = [
        out.AdherenceDay(
            date=i.date,
            training_status=i.status,  # type: ignore[arg-type]
            training_completion=_training_completion(i, today),
            nutrition_completion=nutrition.get(i.date),
        )
        for i in infos
    ]
    grouped: dict[dt.date, list[out.AdherenceDay]] = defaultdict(list)
    for day in days:
        grouped[engine.week_start(day.date)].append(day)
    weeks = [
        out.AdherenceWeek(
            week_start=monday,
            sessions_planned=sum(1 for d in items if d.training_status != "rest"),
            sessions_done=sum(1 for d in items if d.training_status == "done"),
            training_completion=engine.mean_ratio(d.training_completion for d in items),
            nutrition_completion=engine.mean_ratio(d.nutrition_completion for d in items),
        )
        for monday, items in sorted(grouped.items())
    ]
    return out.AdherenceChart(from_=start, to=end, days=days, weeks=weeks)


# ───────────── weekly summary ─────────────


def _weights(
    db: Session, athlete_id: uuid.UUID, start: dt.date, end: dt.date
) -> list[tuple[dt.date, float]]:
    return [
        (d, float(w))
        for d, w in db.execute(
            select(BodyMetric.date, BodyMetric.weight_kg).where(
                BodyMetric.user_id == athlete_id,
                BodyMetric.date.between(start, end),
                BodyMetric.weight_kg.is_not(None),
            )
        )
        if w is not None
    ]


def _round(value: float | None, places: int = WEIGHT_DECIMALS) -> float | None:
    return None if value is None else round(value, places)


def weekly_summary(
    db: Session, user: User, week_start: dt.date | None, now: dt.datetime
) -> out.WeeklySummary:
    today = local_today(now, user.timezone)
    monday = week_start or engine.week_start(today)
    if monday.weekday() != 0:
        raise ProblemError(400, "bad_request", "`week_start` must be a Monday.")
    sunday = monday + dt.timedelta(days=6)
    infos = calendar.training_days(db, user, monday, sunday, today)
    completions = [_training_completion(i, today) for i in infos]
    elapsed_end = min(sunday, today)
    energy = (
        training_log.range_energy(db, user, monday, elapsed_end) if elapsed_end >= monday else {}
    )
    # A day counts for the balance only when food was logged; otherwise the balance would be
    # just minus the burned kcal of a day nobody tracked (decision D77).
    balances = {d: e.balance_kcal for d, e in energy.items() if e.eaten.kcal > 0}
    avg_balance = round(sum(balances.values()) / len(balances)) if balances else None
    target_row = athlete.targets_on(db, user.id, elapsed_end if elapsed_end >= monday else monday)
    days = [monday + dt.timedelta(days=n) for n in range(7)]
    averages = engine.rolling_weight_average(
        _weights(db, user.id, monday - dt.timedelta(days=6), sunday), days
    )
    start_avg = averages[0]
    end_avg = averages[(elapsed_end - monday).days] if elapsed_end >= monday else None
    change = None if start_avg is None or end_avg is None else end_avg - start_avg
    return out.WeeklySummary(
        week_start=monday,
        week_end=sunday,
        sessions_planned=sum(1 for i in infos if i.status != "rest"),
        sessions_done=sum(1 for i in infos if i.status == "done"),
        sessions_missed=sum(1 for i in infos if i.status == "missed"),
        avg_completion=engine.mean_ratio(completions),
        avg_daily_balance_kcal=avg_balance,
        target_daily_balance_kcal=target_row.target_balance_kcal if target_row else None,
        weight_avg_start_kg=_round(start_avg),
        weight_avg_end_kg=_round(end_avg),
        weight_change_kg=_round(change),
        sparklines=out.Sparklines(
            daily_balance_kcal=[out.DatedValue(date=d, value=balances.get(d)) for d in days],
            training_completion=[
                out.DatedValue(date=d, value=c) for d, c in zip(days, completions, strict=True)
            ],
            weight_avg_kg=[
                out.DatedValue(date=d, value=_round(a if d <= today else None))
                for d, a in zip(days, averages, strict=True)
            ],
        ),
    )


# ───────────── body ─────────────


def body_chart(db: Session, user: User, weeks: int, now: dt.datetime) -> out.BodyChart:
    today = local_today(now, user.timezone)
    start = _range_start(today, weeks)
    rows = db.execute(
        select(BodyMetric.date, BodyMetric.weight_kg, BodyMetric.body_fat_pct)
        .where(
            BodyMetric.user_id == user.id,
            BodyMetric.date.between(start - dt.timedelta(days=6), today),
        )
        .order_by(BodyMetric.date)
    ).all()
    in_range = [
        r
        for r in rows
        if r.date >= start and (r.weight_kg is not None or r.body_fat_pct is not None)
    ]
    averages = engine.rolling_weight_average(
        [(r.date, float(r.weight_kg)) for r in rows if r.weight_kg is not None],
        [r.date for r in in_range],
    )
    return out.BodyChart(
        weeks=weeks,
        points=[
            out.BodyChartPoint(
                date=r.date,
                weight_kg=None if r.weight_kg is None else float(r.weight_kg),
                weight_avg_7d_kg=_round(avg),
                body_fat_pct=None if r.body_fat_pct is None else float(r.body_fat_pct),
            )
            for r, avg in zip(in_range, averages, strict=True)
        ],
    )
