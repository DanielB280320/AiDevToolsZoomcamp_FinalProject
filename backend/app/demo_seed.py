"""F-demo seed (#51, D50): one athlete with 8 weeks of history and one linked coach.

Run by `make seed-demo` (`python -m app.cli.seed_demo`) after the migration step, never on app
start. Everything is written through the same services the API uses (onboarding, plan
generation, set and meal logging, suggestions, coach links), once per past day with that day's
clock, so the data is valid against the engines and the history rules (targets snapshots, edit
window, plan versions).

Idempotent: when the demo accounts exist and the coach link is active (the last step), nothing is
written. A run that died half-way leaves no active link; the next run removes the two demo
accounts (their rows cascade) and builds them again. Only these two emails are ever touched.

The history is a fixed pattern, not random, so two seeded databases hold the same history
relative to "today". Test data only: the credentials below are public in the README.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.errors import ProblemError
from app.models import (
    BodyMetric,
    CoachLink,
    Exercise,
    ExtraActivity,
    Food,
    MealLog,
    SetLog,
    Suggestion,
    TrainingSession,
    User,
)
from app.schemas.athlete import AthleteProfileInput, OnboardingBodyMetric, OnboardingRequest
from app.schemas.body import BodyMetricInput
from app.schemas.foods import FoodGrams
from app.schemas.logging import ActivityInput, SetLogInput
from app.schemas.meal_log import MealLogInput
from app.schemas.users import SignUpRequest
from app.services import accounts, athlete, body, coach_links, meal_log, suggestions, training_log
from app.services.calendar import get_day
from app.services.clock import local_today
from app.telemetry import Telemetry, get_logger

logger = get_logger(__name__)

ATHLETE_EMAIL = "demo.athlete@fitwise.test"
COACH_EMAIL = "demo.coach@fitwise.test"
# Test data only. Documented in the README; never use it for a real account.
DEMO_PASSWORD = "demo-password-123"  # noqa: S105
TIMEZONE = "Europe/Madrid"
HISTORY_DAYS = 56  # 8 weeks; the onboarding day is `today - HISTORY_DAYS`
TRAIN_DAYS = ("mon", "tue", "thu", "sat")
# Sessions at least this old get their suggestions decided; newer ones stay pending.
DECIDE_AFTER_DAYS = 8
MISSED_EVERY = 9  # every 9th training day is not done
PARTIAL_EVERY = 5  # every 5th done session skips the last set of each exercise
WEIGH_EVERY = 5  # days between weigh-ins
SKIP_MEAL_DAY_EVERY = 8  # days without any meal log
START_KG = 82.0
# Total loss stays under the 2 % recalculation threshold, so no recalc suggestion is created.
LOSS_KG = 1.2
WOBBLE_KG = (0.0, 0.2, -0.1, 0.1, -0.2)


@dataclass(frozen=True)
class DemoCounts:
    users: int
    sessions_done: int
    sessions_planned: int
    set_logs: int
    meal_log_days: int
    weigh_ins: int
    activities: int
    suggestions_pending: int
    suggestions_decided: int


def _at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), ZoneInfo(TIMEZONE)).astimezone(dt.UTC)


def _find(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email))


def _is_complete(db: Session) -> bool:
    athlete_user, coach = _find(db, ATHLETE_EMAIL), _find(db, COACH_EMAIL)
    if athlete_user is None or coach is None:
        return False
    return (
        db.scalar(
            select(CoachLink.id).where(
                CoachLink.athlete_id == athlete_user.id,
                CoachLink.coach_id == coach.id,
                CoachLink.status == "active",
            )
        )
        is not None
    )


def _sign_up(db: Session, email: str, name: str, role: str, now: dt.datetime) -> User:
    return accounts.sign_up(
        db,
        SignUpRequest(
            email=email,
            password=DEMO_PASSWORD,
            display_name=name,
            role=role,  # type: ignore[arg-type]
            birth_date=dt.date(1992, 6, 15),
            units="metric",
            timezone=TIMEZONE,
            accept_disclaimer=True,
        ),
        now,
    )


def _onboard(db: Session, user: User, now: dt.datetime, telemetry: Telemetry) -> None:
    athlete.onboard(
        db,
        user,
        OnboardingRequest(
            profile=AthleteProfileInput(
                sex="male",
                height_cm=178,
                lifestyle="lightly_active",
                goal="recomposition",
                experience="intermediate",
                days_per_week=len(TRAIN_DAYS),
                preferred_days=list(TRAIN_DAYS),  # type: ignore[arg-type]
                session_minutes=60,
                equipment="full_gym",
                diet="omnivore",
                meals_per_day=4,
            ),
            body_metric=OnboardingBodyMetric(weight_kg=START_KG, body_fat_method="skip"),
        ),
        now,
        telemetry,
    )


def _log_session(
    db: Session, user: User, session_id: object, partial: bool, now: dt.datetime
) -> list[Suggestion]:
    row = db.get(TrainingSession, session_id)
    assert row is not None  # noqa: S101 - just materialised
    day, _ = training_log.load_day(db, row)
    for planned in day.exercises:
        for set_no in range(1, planned.sets + 1):
            skip = partial and set_no == planned.sets and planned.sets > 1
            training_log.log_set(
                db,
                user,
                row.id,
                SetLogInput(
                    exercise_id=planned.exercise_id,
                    planned_exercise_id=planned.id,
                    set_no=set_no,
                    skipped=skip,
                    as_planned=not skip,
                ),
                now,
            )
    finish = now + dt.timedelta(minutes=45)
    training_log.finish_session(db, user, row.id, None, finish)
    return suggestions.refresh_for_session(db, user, row.id, suggestions.DEFAULT_ENGINE, finish)


def _decide(db: Session, user: User, created: Sequence[Suggestion], now: dt.datetime) -> None:
    """Accept the first suggestion (the plan moves on, like a real user would), reject the rest."""
    for position, row in enumerate(created):
        if position == 0:
            try:
                suggestions.accept(db, user, user, row.id, None, now)
                continue
            except ProblemError:
                db.rollback()
        suggestions.reject(db, user, user, row.id, now)


def _log_meals(
    db: Session, user: User, day: dt.date, index: int, extra_food: Food, now: dt.datetime
) -> None:
    _, planned = meal_log.planned_meals(db, user, day)
    for n, meal in enumerate(planned):
        status = "skipped" if (index + n) % 11 == 0 else "eaten"
        meal_log.log_meal(
            db,
            user,
            MealLogInput(date=day, planned_meal_id=meal.id, status=status),  # type: ignore[arg-type]
            now,
        )
    if index % 6 == 2:
        meal_log.log_meal(
            db,
            user,
            MealLogInput(
                date=day,
                planned_meal_id=None,
                status="extra",
                slot="snack",
                items=[FoodGrams(food_id=extra_food.id, grams=120)],
            ),
            now,
        )


def _history(db: Session, user: User, today: dt.date, telemetry: Telemetry) -> None:
    foods = db.scalars(select(Food).where(Food.owner_id.is_(None)).order_by(Food.name)).first()
    cardio = db.scalars(
        select(Exercise)
        .where(Exercise.owner_id.is_(None), Exercise.type == "timed")
        .order_by(Exercise.name)
    ).first()
    if foods is None or cardio is None:
        raise RuntimeError("the exercise and food catalogue is empty; run the migration step first")
    start = today - dt.timedelta(days=HISTORY_DAYS)
    trained = 0
    for offset in range(1, HISTORY_DAYS):  # up to yesterday; today stays open for the demo
        day = start + dt.timedelta(days=offset)
        if offset % WEIGH_EVERY == 0:
            kg = START_KG - LOSS_KG * offset / HISTORY_DAYS + WOBBLE_KG[offset % len(WOBBLE_KG)]
            body.log_metric(
                db,
                user,
                BodyMetricInput(date=day, weight_kg=round(kg, 1)),
                _at(day, 7, 30),
                telemetry,
            )
        if offset % 17 == 9:
            training_log.log_activity(
                db, user, ActivityInput(date=day, exercise_id=cardio.id, minutes=30), _at(day, 12)
            )
        view = get_day(db, user, day.isoformat(), _at(day, 8))
        if view.session is not None:
            trained += 1
            if trained % MISSED_EVERY != 0:
                partial = trained % PARTIAL_EVERY == 0
                created = _log_session(db, user, view.session.id, partial, _at(day, 18))
                if (today - day).days >= DECIDE_AFTER_DAYS:
                    _decide(db, user, created, _at(day, 19))
        if offset % SKIP_MEAL_DAY_EVERY != 5:
            _log_meals(db, user, day, offset, foods, _at(day, 21))


def counts(db: Session) -> DemoCounts:
    athlete_user = _find(db, ATHLETE_EMAIL)
    assert athlete_user is not None  # noqa: S101
    uid = athlete_user.id

    def number(query: object) -> int:
        return int(db.scalar(query) or 0)  # type: ignore[call-overload]

    return DemoCounts(
        users=number(
            select(func.count(User.id)).where(
                func.lower(User.email).in_((ATHLETE_EMAIL, COACH_EMAIL))
            )
        ),
        sessions_done=number(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.athlete_id == uid, TrainingSession.status == "done"
            )
        ),
        sessions_planned=number(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.athlete_id == uid, TrainingSession.status == "planned"
            )
        ),
        set_logs=number(
            select(func.count(SetLog.id))
            .join(TrainingSession, TrainingSession.id == SetLog.session_id)
            .where(TrainingSession.athlete_id == uid)
        ),
        meal_log_days=number(
            select(func.count(func.distinct(MealLog.date))).where(MealLog.athlete_id == uid)
        ),
        weigh_ins=number(
            select(func.count(BodyMetric.id)).where(
                BodyMetric.user_id == uid, BodyMetric.weight_kg.is_not(None)
            )
        ),
        activities=number(
            select(func.count(ExtraActivity.id)).where(ExtraActivity.athlete_id == uid)
        ),
        suggestions_pending=number(
            select(func.count(Suggestion.id)).where(
                Suggestion.athlete_id == uid, Suggestion.status == "pending"
            )
        ),
        suggestions_decided=number(
            select(func.count(Suggestion.id)).where(
                Suggestion.athlete_id == uid, Suggestion.status != "pending"
            )
        ),
    )


def seed_demo(db: Session, now: dt.datetime, telemetry: Telemetry) -> tuple[DemoCounts, bool]:
    """Create the demo athlete, coach and history. Returns the counts and whether it wrote."""
    if _is_complete(db):
        return counts(db), False
    # Half-built from an earlier failed run: start again (cascades remove everything of theirs).
    db.execute(delete(User).where(func.lower(User.email).in_((ATHLETE_EMAIL, COACH_EMAIL))))
    db.commit()

    today = local_today(now, TIMEZONE)
    start = _at(today - dt.timedelta(days=HISTORY_DAYS), 8)
    coach = _sign_up(db, COACH_EMAIL, "Demo Coach", "coach", start)
    user = _sign_up(db, ATHLETE_EMAIL, "Demo Athlete", "athlete", start)
    _onboard(db, user, start, telemetry)
    _history(db, user, today, telemetry)
    link = coach_links.request_link(db, user, coach.id, now)
    coach_links.decide(db, coach, link.id, approve=True, now=now)
    return counts(db), True
