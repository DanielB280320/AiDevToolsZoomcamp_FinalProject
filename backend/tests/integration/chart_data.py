"""Direct database seeding for the chart tests (F15): a plan, finished sessions with target
snapshots, meal logs, weigh-ins. Rows are written with the ORM so a year of history is cheap."""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BodyMetric,
    Exercise,
    ExtraActivity,
    Food,
    Meal,
    MealDay,
    MealLog,
    MealLogItem,
    PlannedExercise,
    PlannedMeal,
    SetLog,
    Targets,
    TrainingDay,
    TrainingSession,
    User,
)
from app.seed import run_seed
from app.services.plans import (
    NewMealDay,
    NewPlannedExercise,
    NewPlannedMeal,
    NewTrainingDay,
    create_plan_version,
)
from tests.integration.auth_helpers import NOW, Api

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SLOTS = ("breakfast", "lunch", "dinner")


@dataclass
class Seeded:
    uid: uuid.UUID
    strength_id: uuid.UUID
    timed_id: uuid.UUID
    planned_id: uuid.UUID
    plan_id: uuid.UUID
    day_ids: dict[str, uuid.UUID]
    plan_created: dt.datetime


def seed_plan(
    api: Api,
    *,
    email: str = "ana@x.test",
    days_ago: int = 60,
    weekdays: tuple[str, ...] = ("mon", "thu", "fri"),
) -> Seeded:
    assert api.signup(email=email).status_code == 201
    created = NOW - dt.timedelta(days=days_ago)
    with Session(api.app.state.engine) as db:
        run_seed(db)
        uid = db.scalars(select(User.id).where(User.email == email)).one()
        strength = db.scalars(
            select(Exercise)
            .where(Exercise.owner_id.is_(None), Exercise.type == "strength")
            .order_by(Exercise.name)
        ).first()
        timed = db.scalars(
            select(Exercise)
            .where(Exercise.owner_id.is_(None), Exercise.type == "timed")
            .order_by(Exercise.name)
        ).first()
        picked = list(db.scalars(select(Meal).where(Meal.owner_id.is_(None)).order_by(Meal.name)))[
            :3
        ]
        assert strength is not None and timed is not None and len(picked) == 3
        plan = create_plan_version(
            db,
            athlete_id=uid,
            author_id=uid,
            source="generated",
            days=[
                NewTrainingDay(
                    w,
                    f"Day {w}",
                    [
                        NewPlannedExercise(
                            strength.id,
                            3,
                            90,
                            "linear",
                            2.5,
                            reps_min=8,
                            reps_max=8,
                            target_weight_kg=50.0,
                        ),
                        NewPlannedExercise(timed.id, 1, 60, "linear", 0, target_seconds=600),
                    ],
                )
                for w in weekdays
            ],
            meal_days=[
                NewMealDay(
                    w, [NewPlannedMeal(s, m.id, 1.0) for s, m in zip(SLOTS, picked, strict=True)]
                )
                for w in WEEKDAYS
            ],
            now=created,
        )
        db.add(
            Targets(
                user_id=uid,
                valid_from=(created + dt.timedelta(hours=3)).date(),
                bmr_formula="mifflin_st_jeor",
                bmr_kcal=1700,
                lifestyle_factor=1.4,
                baseline_kcal=2400,
                planned_exercise_kcal_per_day=0,
                goal_adjustment_pct=-10,
                kcal=2100,
                protein_g=150,
                carbs_g=220,
                fat_g=60,
                target_balance_kcal=-300,
                floor_applied=False,
                floor_kcal=1500,
                carbs_clamped=False,
                weight_used_kg=80,
                body_fat_pct_used=None,
                explanation="test",
                inputs={},
                created_at=created,
            )
        )
        db.commit()
        days = {
            d.weekday: d.id
            for d in db.scalars(select(TrainingDay).where(TrainingDay.plan_id == plan.id))
        }
        planned = db.scalars(
            select(PlannedExercise).where(PlannedExercise.exercise_id == strength.id)
        ).first()
        assert planned is not None
        return Seeded(uid, strength.id, timed.id, planned.id, plan.id, days, created)


def add_session(
    db: Session,
    seed: Seeded,
    day: dt.date,
    *,
    sets: list[tuple[int, float, int, float]] | None = None,
    status: str = "done",
    completion: float | None = 0.9,
    timed_seconds: int | None = None,
    skipped_sets: tuple[int, ...] = (),
) -> TrainingSession:
    """A session on `day` (its weekday must be in the plan). `sets` are
    (reps, weight_kg, target_reps, target_weight_kg) per strength set."""
    when = dt.datetime.combine(day, dt.time(10, 0), dt.UTC)
    row = TrainingSession(
        athlete_id=seed.uid,
        plan_id=seed.plan_id,
        training_day_id=seed.day_ids[WEEKDAYS[day.weekday()]],
        date=day,
        status=status,
        started_at=when,
        finished_at=when if status == "done" else None,
        completion=completion,
        kcal=300 if status == "done" else None,
        created_at=when,
    )
    db.add(row)
    db.flush()
    for n, (reps, kg, target_reps, target_kg) in enumerate(sets or [], start=1):
        skipped = n in skipped_sets
        db.add(
            SetLog(
                session_id=row.id,
                planned_exercise_id=seed.planned_id,
                exercise_id=seed.strength_id,
                set_no=n,
                skipped=skipped,
                target_reps=target_reps,
                target_weight_kg=target_kg,
                reps=None if skipped else reps,
                weight_kg=None if skipped else kg,
                logged_at=when,
            )
        )
    if timed_seconds is not None:
        db.add(
            SetLog(
                session_id=row.id,
                exercise_id=seed.timed_id,
                set_no=1,
                target_seconds=600,
                seconds=timed_seconds,
                logged_at=when,
            )
        )
    return row


def add_meals(db: Session, seed: Seeded, day: dt.date, statuses: tuple[str, ...]) -> None:
    """One log per planned meal of that weekday's plan, with the given statuses."""
    food = db.scalars(select(Food).where(Food.source == "seed").order_by(Food.name)).first()
    assert food is not None
    keys = db.scalars(
        select(PlannedMeal)
        .join(MealDay, MealDay.id == PlannedMeal.meal_day_id)
        .where(MealDay.plan_id == seed.plan_id, MealDay.weekday == WEEKDAYS[day.weekday()])
        .order_by(PlannedMeal.position)
    ).all()
    when = dt.datetime.combine(day, dt.time(12, 0), dt.UTC)
    for meal, status in zip(keys, statuses, strict=False):
        log = MealLog(
            athlete_id=seed.uid,
            date=day,
            planned_meal_id=meal.id,
            status=status,
            slot=meal.slot,
            meal_key=meal.meal_key,
            logged_at=when,
        )
        db.add(log)
        db.flush()
        if status != "skipped":
            db.add(MealLogItem(meal_log_id=log.id, food_id=food.id, position=1, grams=150))


def add_weight(
    db: Session, seed: Seeded, day: dt.date, kg: float | None, fat: float | None = None
) -> None:
    db.add(BodyMetric(user_id=seed.uid, date=day, weight_kg=kg, body_fat_pct=fat, created_at=NOW))


def add_activity(db: Session, seed: Seeded, day: dt.date) -> None:
    db.add(
        ExtraActivity(
            athlete_id=seed.uid,
            date=day,
            exercise_id=seed.timed_id,
            minutes=30,
            kcal=200,
            created_at=NOW,
        )
    )
