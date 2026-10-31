"""`GET /coach/athletes`: the coach's client list with F16.5 "needs attention" (spec F16, D83).

A fixed number of queries whatever the number of clients (links with users, active plans, first
plan dates, sessions in the window, the three kinds of log, suggestions); everything per athlete
is then derived in Python, against that athlete's own "today" (rule 5). The rules and the order
are the pure `engines.coach_attention`.

Training adherence over the 7 days ending today mirrors the adherence chart: planned days (from
the active plan's weekly template, or the stored session when there is one) count as 0 when
missed and by their completion when started or done; a planned day that is today and untouched
has no value yet. `None` when no day has a value. Nothing here logs: names and adherence are
health data (spec section 6.5).
"""

import datetime as dt
import uuid
from collections import defaultdict
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.engines import charts as chart_engine
from app.engines import coach_attention as attention
from app.engines.constants import ATTENTION_ADHERENCE_WINDOW_DAYS, ATTENTION_DELOAD_WINDOW_DAYS
from app.models import (
    BodyMetric,
    CoachLink,
    MealLog,
    Plan,
    SetLog,
    Suggestion,
    TrainingDay,
    TrainingSession,
    User,
)
from app.models.plan import WEEKDAYS
from app.schemas import coach as out
from app.schemas.users import UserRef
from app.services.clock import local_today

_Session = tuple[dt.date, dt.date | None, str, float | None]  # date, original, status, completion


def _adherence(
    today: dt.date,
    weekdays: set[str],
    template_start: dt.date | None,
    sessions: list[_Session],
) -> float | None:
    """Mean completion over `today - 6 .. today` (see module docstring)."""
    by_date = {s[0]: s for s in sessions}
    moved_away = {s[1] for s in sessions if s[1] is not None and s[1] != s[0]}
    values: list[float | None] = []
    for offset in range(ATTENTION_ADHERENCE_WINDOW_DAYS):
        day = today - dt.timedelta(days=offset)
        row = by_date.get(day)
        if row is not None:
            status, completion = row[2], row[3]
        elif (
            template_start is not None
            and day >= template_start
            and WEEKDAYS[day.weekday()] in weekdays
            and day not in moved_away
        ):
            status, completion = "planned", None
        else:
            continue
        if status == "planned":
            values.append(0.0 if day < today else None)  # missed, or today still to do
        else:
            values.append(completion)
    return chart_engine.mean_ratio(values)


def list_athletes(db: Session, coach: User, now: dt.datetime) -> out.CoachAthleteList:
    links = db.execute(
        select(CoachLink, User)
        .join(User, User.id == CoachLink.athlete_id)
        .where(CoachLink.coach_id == coach.id, CoachLink.status == "active")
    ).all()
    if not links:
        return out.CoachAthleteList(items=[])
    ids = [user.id for _, user in links]
    zones = {user.id: ZoneInfo(user.timezone) for _, user in links}
    today = {user.id: local_today(now, user.timezone) for _, user in links}
    low = min(today.values()) - dt.timedelta(days=ATTENTION_ADHERENCE_WINDOW_DAYS)
    high = max(today.values())

    weekdays: dict[uuid.UUID, set[str]] = defaultdict(set)
    for athlete_id, weekday in db.execute(
        select(Plan.athlete_id, TrainingDay.weekday)
        .join(TrainingDay, TrainingDay.plan_id == Plan.id)
        .where(Plan.athlete_id.in_(ids), Plan.active.is_(True))
    ):
        weekdays[athlete_id].add(weekday)
    template_start: dict[uuid.UUID, dt.date] = {}
    for athlete_id, first in db.execute(
        select(Plan.athlete_id, func.min(Plan.created_at))
        .where(Plan.athlete_id.in_(ids))
        .group_by(Plan.athlete_id)
    ):
        template_start[athlete_id] = first.astimezone(zones[athlete_id]).date()
    sessions: dict[uuid.UUID, list[_Session]] = defaultdict(list)
    for athlete_id, date, original, status, completion in db.execute(
        select(
            TrainingSession.athlete_id,
            TrainingSession.date,
            TrainingSession.original_date,
            TrainingSession.status,
            TrainingSession.completion,
        ).where(
            TrainingSession.athlete_id.in_(ids),
            or_(
                TrainingSession.date.between(low, high),
                TrainingSession.original_date.between(low, high),
            ),
        )
    ):
        sessions[athlete_id].append((date, original, status, completion))

    last_log: dict[uuid.UUID, dt.date] = {}

    def _note(athlete_id: uuid.UUID, day: dt.date | None) -> None:
        if day is not None and (athlete_id not in last_log or day > last_log[athlete_id]):
            last_log[athlete_id] = day

    for athlete_id, day in db.execute(
        select(TrainingSession.athlete_id, func.max(TrainingSession.date))
        .join(SetLog, SetLog.session_id == TrainingSession.id)
        .where(TrainingSession.athlete_id.in_(ids))
        .group_by(TrainingSession.athlete_id)
    ):
        _note(athlete_id, day)
    for athlete_id, day in db.execute(
        select(MealLog.athlete_id, func.max(MealLog.date))
        .where(MealLog.athlete_id.in_(ids))
        .group_by(MealLog.athlete_id)
    ):
        _note(athlete_id, day)
    for athlete_id, day in db.execute(
        select(BodyMetric.user_id, func.max(BodyMetric.date))
        .where(BodyMetric.user_id.in_(ids))
        .group_by(BodyMetric.user_id)
    ):
        _note(athlete_id, day)

    pending: dict[uuid.UUID, int] = defaultdict(int)
    deload_pending: set[uuid.UUID] = set()
    deload_applied: dict[uuid.UUID, dt.date] = {}
    cutoff = now - dt.timedelta(days=ATTENTION_DELOAD_WINDOW_DAYS + 2)
    for athlete_id, status, rule, decided_at in db.execute(
        select(
            Suggestion.athlete_id, Suggestion.status, Suggestion.rule, Suggestion.decided_at
        ).where(
            Suggestion.athlete_id.in_(ids),
            or_(
                Suggestion.status == "pending",
                (Suggestion.rule == "deload")
                & (Suggestion.status == "accepted")
                & (Suggestion.decided_at >= cutoff),
            ),
        )
    ):
        if status == "pending":
            pending[athlete_id] += 1
            if rule == "deload":
                deload_pending.add(athlete_id)
        elif decided_at is not None:
            day = decided_at.astimezone(zones[athlete_id]).date()
            if athlete_id not in deload_applied or day > deload_applied[athlete_id]:
                deload_applied[athlete_id] = day

    rows: list[out.CoachAthleteSummary] = []
    for link, user in links:
        adherence = _adherence(
            today[user.id],
            weekdays.get(user.id, set()),
            template_start.get(user.id),
            sessions.get(user.id, []),
        )
        result = attention.evaluate(
            attention.AttentionInput(
                today=today[user.id],
                linked_since=link.updated_at.astimezone(zones[user.id]).date(),
                training_adherence_7d=adherence,
                last_log_date=last_log.get(user.id),
                deload_pending=user.id in deload_pending,
                deload_applied_on=deload_applied.get(user.id),
            )
        )
        rows.append(
            out.CoachAthleteSummary(
                athlete=UserRef.model_validate(
                    {"id": user.id, "display_name": user.display_name, "role": user.role}
                ),
                units=user.units,  # type: ignore[arg-type]
                timezone=user.timezone,
                link_id=link.id,
                linked_since=link.updated_at,
                needs_attention=result.needs_attention,
                attention_reasons=list(result.reasons),
                training_adherence_7d=adherence,
                last_log_date=last_log.get(user.id),
                pending_suggestion_count=pending.get(user.id, 0),
            )
        )
    ordered = attention.order_athletes(
        rows,
        needs_attention=lambda r: r.needs_attention,
        display_name=lambda r: r.athlete.display_name,
        athlete_id=lambda r: r.athlete.id,
    )
    return out.CoachAthleteList(items=ordered)
