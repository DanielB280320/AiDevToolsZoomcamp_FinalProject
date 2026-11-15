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
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines import charts as engine
from app.engines import constants as consts
from app.engines.nutrition_completion import nutrition_completion
from app.errors import ProblemError
from app.models import (
    BodyMetric,
    Exercise,
    MealDay,
    MealLog,
    Plan,
    PlannedMeal,
    SetLog,
    TrainingSession,
    User,
)
from app.models.plan import WEEKDAYS, plan_events
from app.schemas import charts as out
from app.schemas.plans import ExerciseSummary
from app.services import athlete, calendar, training_log
from app.services.calendar import TrainingDayInfo, utc_midnight_after
from app.services.clock import local_today

WEEKS_CHOICES = (4, 12, 26, 52)
MAX_ADHERENCE_DAYS = consts.CHART_RANGE_MAX_DAYS
WEIGHT_DECIMALS = 2


def check_weeks(weeks: int) -> int:
    if weeks not in WEEKS_CHOICES:
        raise ProblemError(400, "bad_request", "`weeks` must be one of 4, 12, 26 or 52.")
    return weeks


def _range_start(today: dt.date, weeks: int) -> dt.date:
    return today - dt.timedelta(days=weeks * 7 - 1)


def check_range(start: dt.date, end: dt.date) -> None:
    """The 400s shared by adherence, the period summary and the `from`/`to` of the other charts."""
    if start > end:
        raise ProblemError(400, "invalid_range", "`from` must not be after `to`.")
    if (end - start).days + 1 > MAX_ADHERENCE_DAYS:
        raise ProblemError(
            400, "range_too_large", f"The range may cover at most {MAX_ADHERENCE_DAYS} days."
        )


def optional_range(start: dt.date | None, end: dt.date | None) -> tuple[dt.date, dt.date] | None:
    """`from` and `to` of the exercise and body charts (D109): both or neither."""
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ProblemError(400, "bad_request", "`from` and `to` must be given together.")
    check_range(start, end)
    return start, end


def _weeks_covered(start: dt.date, end: dt.date) -> int:
    return -(-((end - start).days + 1) // 7)


# ───────────── session detail ─────────────


def session_chart(
    db: Session, user: User, session_id: uuid.UUID, now: dt.datetime
) -> out.SessionChart:
    row = calendar.session_of(db, user, session_id)
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


def _group_by_session(
    rows: Iterable[tuple[SetLog, dt.date]],
) -> dict[uuid.UUID, tuple[dt.date, list[engine.LoggedSet]]]:
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
    return by_session


def personal_records(
    db: Session, athlete_id: uuid.UUID, session: TrainingSession, timed: dict[uuid.UUID, bool]
) -> set[uuid.UUID]:
    """Exercise ids (keys of `timed`) whose top set in `session` is a personal record (D88).

    Computed on read with the F15 chart ranking (`engine.exercise_history`) over the athlete's
    finished sessions plus this one, so an edit or delete of the record-setting set shows at once.
    """
    if not timed:
        return set()
    rows = db.execute(
        select(SetLog, TrainingSession.date)
        .join(TrainingSession, TrainingSession.id == SetLog.session_id)
        .where(
            TrainingSession.athlete_id == athlete_id,
            SetLog.exercise_id.in_(list(timed)),
            SetLog.skipped.is_(False),
            (TrainingSession.status == "done") | (TrainingSession.id == session.id),
        )
        .order_by(TrainingSession.date, TrainingSession.id)
    ).all()
    records: set[uuid.UUID] = set()
    for exercise_id, is_timed in timed.items():
        mine = [(log, day) for log, day in rows if log.exercise_id == exercise_id]
        history = engine.exercise_history(
            ((str(sid), day, sets) for sid, (day, sets) in _group_by_session(mine).items()),
            timed=is_timed,
        )
        if any(p.session_id == str(session.id) and p.is_pr for p in history):
            records.add(exercise_id)
    return records


def exercise_chart(
    db: Session,
    user: User,
    exercise_id: uuid.UUID,
    weeks: int,
    now: dt.datetime,
    period: tuple[dt.date, dt.date] | None = None,
) -> out.ExerciseChart:
    exercise = training_log._visible_exercise(db, user, exercise_id)
    today = local_today(now, user.timezone)
    start = _range_start(today, weeks)
    end = today
    if period is not None:  # D109: explicit days, `weeks` ignored
        start, end = period
        weeks = _weeks_covered(start, end)
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
    by_session = _group_by_session(rows)
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
        if start <= p.date <= end
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
    events = plan_events()
    versions = db.execute(
        select(MealDay.id, MealDay.weekday, events.c.at)
        .join(Plan, Plan.id == MealDay.plan_id)
        .join(events, events.c.plan_id == Plan.id)
        .where(Plan.athlete_id == user.id)
        .order_by(events.c.at.desc(), Plan.version.desc())
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
    check_range(start, end)
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


def body_chart(
    db: Session,
    user: User,
    weeks: int,
    now: dt.datetime,
    period: tuple[dt.date, dt.date] | None = None,
) -> out.BodyChart:
    today = local_today(now, user.timezone)
    start = _range_start(today, weeks)
    end = today
    if period is not None:  # D109: explicit days, `weeks` ignored
        start, end = period
        weeks = _weeks_covered(start, end)
        end = min(end, today)
    rows = db.execute(
        select(BodyMetric.date, BodyMetric.weight_kg, BodyMetric.body_fat_pct)
        .where(
            BodyMetric.user_id == user.id,
            BodyMetric.date.between(start - dt.timedelta(days=6), end),
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


# ───────────── period overview (D109) ─────────────


def _volume_and_records(
    db: Session, user: User, today: dt.date
) -> tuple[dict[dt.date, float], dict[dt.date, int]]:
    """Volume (reps x weight of the non-skipped strength sets) and personal records per day of
    the finished sessions up to today. One query over the whole history, because a record is
    measured against every earlier session (D88, as `progress_totals`)."""
    rows = db.execute(
        select(SetLog, TrainingSession.date, Exercise.type)
        .join(TrainingSession, TrainingSession.id == SetLog.session_id)
        .join(Exercise, Exercise.id == SetLog.exercise_id)
        .where(
            TrainingSession.athlete_id == user.id,
            TrainingSession.status == "done",
            TrainingSession.date <= today,
            SetLog.skipped.is_(False),
        )
    ).all()
    by_exercise: dict[uuid.UUID, list[tuple[SetLog, dt.date]]] = defaultdict(list)
    timed: dict[uuid.UUID, bool] = {}
    for log, day, kind in rows:
        by_exercise[log.exercise_id].append((log, day))
        timed[log.exercise_id] = kind == "timed"
    volume: dict[dt.date, float] = defaultdict(float)
    records: dict[dt.date, int] = defaultdict(int)
    for exercise_id, logs in by_exercise.items():
        history = engine.exercise_history(
            ((str(sid), day, sets) for sid, (day, sets) in _group_by_session(logs).items()),
            timed=timed[exercise_id],
        )
        for point in history:
            if not timed[exercise_id]:
                volume[point.date] += point.volume_kg
            if point.is_pr:
                records[point.date] += 1
    return volume, records


def _mean_int(values: list[int]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def period_summary(
    db: Session, user: User, start: dt.date, end: dt.date, now: dt.datetime
) -> out.PeriodSummary:
    """KPIs of `start..end` and of the same number of days before it, with their differences,
    the longest streak and one series point per bucket (F15.6-F15.10, D109).

    Everything is read once for `previous_from..to` (a fixed number of queries whatever the
    length) and sliced per period. Days after the athlete's today contribute nothing.
    """
    check_range(start, end)
    today = local_today(now, user.timezone)
    prev_start, prev_end = engine.previous_period(start, end)
    elapsed_end = min(end, today)
    infos = {i.date: i for i in calendar.training_days(db, user, prev_start, end, today)}
    nutrition = _nutrition_completion(db, user, prev_start, end, today)
    energy = (
        training_log.range_energy(db, user, prev_start, elapsed_end)
        if elapsed_end >= prev_start
        else {}
    )
    volume, records = _volume_and_records(db, user, today)
    averages: dict[dt.date, float | None] = {}
    if elapsed_end >= prev_start:
        span = [
            prev_start + dt.timedelta(days=n) for n in range((elapsed_end - prev_start).days + 1)
        ]
        averages = dict(
            zip(
                span,
                engine.rolling_weight_average(
                    _weights(db, user.id, prev_start - dt.timedelta(days=6), elapsed_end), span
                ),
                strict=True,
            )
        )

    def elapsed(first: dt.date, last: dt.date) -> list[dt.date]:
        last = min(last, today)
        return [first + dt.timedelta(days=n) for n in range((last - first).days + 1)]

    def logged(days: list[dt.date]) -> list[dt.date]:
        # Only days with food logged count for the energy averages (D77).
        return [d for d in days if d in energy and energy[d].eaten.kcal > 0]

    def kpis(first: dt.date, last: dt.date) -> out.PeriodKpis:
        days = elapsed(first, last)
        done = sum(1 for d in days if infos[d].status == "done")
        food_days = logged(days)
        last_day = days[-1] if days else None
        target = athlete.targets_on(db, user.id, last_day) if last_day else None
        start_avg = averages.get(first) if days else None
        end_avg = averages.get(last_day) if last_day else None
        change = None if start_avg is None or end_avg is None else end_avg - start_avg
        per_week = engine.weekly_rate(change, (last_day - first).days) if last_day else None
        return out.PeriodKpis(
            sessions_planned=sum(1 for d in days if infos[d].status != "rest"),
            sessions_done=done,
            sessions_missed=sum(1 for d in days if infos[d].status == "missed"),
            avg_training_completion=engine.mean_ratio(
                _training_completion(infos[d], today) for d in days
            ),
            avg_nutrition_completion=engine.mean_ratio(nutrition.get(d) for d in days),
            active_days=done,
            volume_kg=round(sum(volume.get(d, 0.0) for d in days), WEIGHT_DECIMALS),
            personal_records=sum(records.get(d, 0) for d in days),
            avg_daily_eaten_kcal=_mean_int([energy[d].eaten.kcal for d in food_days]),
            avg_daily_burned_exercise_kcal=_mean_int(
                [
                    energy[d].burned.training_kcal + energy[d].burned.activities_kcal
                    for d in food_days
                ]
            ),
            avg_daily_balance_kcal=_mean_int([energy[d].balance_kcal for d in food_days]),
            target_daily_balance_kcal=target.target_balance_kcal if target else None,
            weight_avg_start_kg=_round(start_avg),
            weight_avg_end_kg=_round(end_avg),
            weight_change_kg=_round(change),
            weight_change_per_week_kg=_round(per_week),
        )

    current = kpis(start, end)
    previous = kpis(prev_start, prev_end)
    deltas = engine.period_deltas(current.model_dump(), previous.model_dump())
    streak = engine.longest_streak((d, infos[d].status) for d in elapsed(start, end))
    kind = engine.bucket_kind((end - start).days + 1)
    series: list[out.PeriodSeriesPoint] = []
    for label in engine.bucket_starts(start, end, kind):
        bucket_end = label if kind == "day" else label + dt.timedelta(days=6)
        days = elapsed(max(label, start), min(bucket_end, end))
        if not days:  # a bucket entirely after today
            continue
        food_days = logged(days)
        series.append(
            out.PeriodSeriesPoint(
                start=label,
                sessions_done=sum(1 for d in days if infos[d].status == "done"),
                sessions_planned=sum(1 for d in days if infos[d].status != "rest"),
                volume_kg=round(sum(volume.get(d, 0.0) for d in days), WEIGHT_DECIMALS),
                training_completion=engine.mean_ratio(
                    _training_completion(infos[d], today) for d in days
                ),
                nutrition_completion=engine.mean_ratio(nutrition.get(d) for d in days),
                balance_kcal=_mean_int([energy[d].balance_kcal for d in food_days]),
                weight_avg_kg=_round(averages.get(days[-1])),
            )
        )
    return out.PeriodSummary(
        from_=start,
        to=end,
        days=(end - start).days + 1,
        previous_from=prev_start,
        previous_to=prev_end,
        bucket=kind,
        current=current,
        previous=previous,
        deltas=out.PeriodDeltas(**deltas.values),
        longest_streak_days=streak.days,
        series=series,
    )


# ───────────── totals to date ─────────────


def progress_totals(db: Session, user: User, now: dt.datetime) -> out.ProgressTotals:
    """All-time figures for Today's overview (F9.5, D101): finished sessions and personal records.

    A personal record is counted with the F15 ranking (`engine.exercise_history`, D76(4), D88):
    once per finished session and exercise whose top set beats every earlier finished session of
    that exercise, the first one included. Two queries, whatever the length of the history.
    """
    today = local_today(now, user.timezone)
    finished = (
        TrainingSession.athlete_id == user.id,
        TrainingSession.status == "done",
        TrainingSession.date <= today,
    )
    sessions_done, first_day = db.execute(
        select(func.count(TrainingSession.id), func.min(TrainingSession.date)).where(*finished)
    ).one()
    rows = db.execute(
        select(SetLog, TrainingSession.date, Exercise.type)
        .join(TrainingSession, TrainingSession.id == SetLog.session_id)
        .join(Exercise, Exercise.id == SetLog.exercise_id)
        .where(*finished, SetLog.skipped.is_(False))
    ).all()
    by_exercise: dict[uuid.UUID, list[tuple[SetLog, dt.date]]] = defaultdict(list)
    timed: dict[uuid.UUID, bool] = {}
    for log, day, kind in rows:
        by_exercise[log.exercise_id].append((log, day))
        timed[log.exercise_id] = kind == "timed"
    records = 0
    for exercise_id, logs in by_exercise.items():
        history = engine.exercise_history(
            ((str(sid), day, sets) for sid, (day, sets) in _group_by_session(logs).items()),
            timed=timed[exercise_id],
        )
        records += sum(1 for point in history if point.is_pr)
    return out.ProgressTotals(
        sessions_done=sessions_done, personal_records=records, first_session_date=first_day
    )
