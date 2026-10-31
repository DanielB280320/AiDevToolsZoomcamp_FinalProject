"""Weekly adaptive calorie suggestion (spec F14, #42).

* `generate(...)` evaluates one athlete for the current local week: the two complete Monday to
  Sunday weeks before this week's Monday, with the pure engine. It stores one pending `calories`
  suggestion when the engine asks for a change and replaces an older still-pending one. It runs at
  most once per athlete and Monday (`inputs.evaluated_on`), so re-running the job is harmless.
* `run_weekly(...)` does that for every onboarded athlete; the ops CLI
  (`python -m app.cli.adaptive_calories`) calls it on Mondays.
* `hint(...)` is the `weigh_in_hint` of the suggestion list: set when this week's check lacked
  weigh-ins (F14.2).
* Accepting is `suggestions._accept_calories`: targets from today and meal portions from today on
  through the shared service of D74; past days are never touched.

Nothing here logs and no span or metric carries values: weights and targets are health data.
"""

import dataclasses
import datetime as dt
import uuid
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engines import adaptive_calories as engine
from app.engines import body_tracking
from app.engines import constants as c
from app.models import AthleteProfile, BodyMetric, Suggestion, User
from app.schemas import suggestions as out
from app.services import athlete, notifications
from app.services.clock import local_today
from app.telemetry import Telemetry

RULE: Final = "adaptive_calories"
WEEK = dt.timedelta(days=7)
HINT_MESSAGE = "Weigh in at least 4 times a week to get an adaptive calorie suggestion."


@dataclasses.dataclass(frozen=True)
class Evaluation:
    evaluated_on: dt.date
    """The Monday of the current local week."""
    week_starts: tuple[dt.date, dt.date]
    weigh_ins: tuple[int, int]
    result: engine.AdaptiveResult
    current_kcal: int


def week_monday(today: dt.date) -> dt.date:
    return today - dt.timedelta(days=today.weekday())


def _weights(
    db: Session, athlete_id: uuid.UUID, start: dt.date, end: dt.date
) -> list[tuple[dt.date, float]]:
    return [
        (d, float(w))
        for d, w in db.execute(
            select(BodyMetric.date, BodyMetric.weight_kg).where(
                BodyMetric.user_id == athlete_id,
                BodyMetric.date >= start,
                BodyMetric.date <= end,
                BodyMetric.weight_kg.is_not(None),
            )
        )
        if w is not None
    ]


def evaluate(db: Session, user: User, today: dt.date) -> Evaluation | None:
    """The engine's verdict for the week of `today`; `None` when the athlete has no targets."""
    profile = db.get(AthleteProfile, user.id)
    current = athlete.targets_on(db, user.id, today)
    if profile is None or current is None:
        return None
    monday = week_monday(today)
    first, second = monday - 2 * WEEK, monday - WEEK
    weights = _weights(
        db, user.id, first - dt.timedelta(days=c.WEIGHT_AVERAGE_WINDOW_DAYS - 1), monday
    )

    def week(start: dt.date) -> engine.WeekTrend:
        last = start + dt.timedelta(days=6)
        return engine.WeekTrend(
            start_avg_kg=body_tracking.seven_day_average(weights, start).average_kg,
            end_avg_kg=body_tracking.seven_day_average(weights, last).average_kg,
            weigh_ins=sum(1 for d, _ in weights if start <= d <= last),
        )

    weeks = (week(first), week(second))
    result = engine.suggest(
        engine.AdaptiveInput(
            goal=profile.goal,
            current_kcal=current.kcal,
            floor_kcal=current.floor_kcal,
            weeks=weeks,
        )
    )
    return Evaluation(
        monday, (first, second), (weeks[0].weigh_ins, weeks[1].weigh_ins), result, current.kcal
    )


def hint(db: Session, user: User, now: dt.datetime) -> out.WeighInHint | None:
    """F14.2: the hint for the current week, or `None` when the weigh-ins were sufficient."""
    if user.role != "athlete":
        return None
    ev = evaluate(db, user, local_today(now, user.timezone))
    if ev is None or not ev.result.insufficient_weigh_ins:
        return None
    return out.WeighInHint(
        message=HINT_MESSAGE,
        evaluated_on=ev.evaluated_on,
        required_per_week=4,
        weeks=[
            out.WeighInWeek(week_start=s, weigh_ins=n)
            for s, n in zip(ev.week_starts, ev.weigh_ins, strict=True)
        ],
    )


def _already_evaluated(db: Session, athlete_id: uuid.UUID, evaluated_on: dt.date) -> bool:
    rows = db.scalars(
        select(Suggestion.inputs).where(
            Suggestion.athlete_id == athlete_id, Suggestion.kind == "calories"
        )
    )
    return any(i.get("evaluated_on") == evaluated_on.isoformat() for i in rows)


def generate(
    db: Session, user: User, now: dt.datetime, telemetry: Telemetry | None = None
) -> Suggestion | None:
    """The pending `calories` suggestion for this week, or `None`. Commits."""
    if user.role != "athlete":
        return None
    # Serialises with weigh-ins, profile edits and accepts of the same athlete.
    db.execute(select(User.id).where(User.id == user.id).with_for_update()).one()
    ev = evaluate(db, user, local_today(now, user.timezone))
    if ev is None or ev.result.action == "none" or _already_evaluated(db, user.id, ev.evaluated_on):
        db.rollback()
        return None
    r = ev.result
    db.execute(
        delete(Suggestion).where(
            Suggestion.athlete_id == user.id,
            Suggestion.kind == "calories",
            Suggestion.status == "pending",
        )
    )
    row = Suggestion(
        athlete_id=user.id,
        kind="calories",
        status="pending",
        rule=RULE,
        reason=r.reason,
        inputs={
            "evaluated_on": ev.evaluated_on.isoformat(),
            "week_starts": [d.isoformat() for d in ev.week_starts],
            "weigh_ins": list(ev.weigh_ins),
            "action": r.action,
        },
        payload={
            "current_kcal": ev.current_kcal,
            "proposed_kcal": r.proposed_kcal,
            "delta_kcal": r.delta_kcal,
            "floor_applied": False,
            "expected_weekly_change_pct": r.expected_weekly_change_pct,
            "tolerance_pct": r.tolerance_pct,
            "observed_weekly_change_pct": list(r.observed_weekly_change_pct),
            "applied_kcal": None,
        },
        created_at=now,
    )
    db.add(row)
    db.flush()
    notifications.notify(db, user.id, "calorie_suggestion", {"suggestion_id": row.id}, now)
    db.commit()
    if telemetry is not None:
        telemetry.metrics.suggestion_generated("calories", RULE)
    return row


def run_weekly(db: Session, now: dt.datetime, telemetry: Telemetry | None = None) -> int:
    """Generate for every athlete with targets; returns how many suggestions were created."""
    ids = list(
        db.scalars(
            select(User.id)
            .join(AthleteProfile, AthleteProfile.user_id == User.id)
            .order_by(User.id)
        )
    )
    created = 0
    for user_id in ids:
        user = db.get(User, user_id)
        if user is not None and generate(db, user, now, telemetry) is not None:
            created += 1
    return created
