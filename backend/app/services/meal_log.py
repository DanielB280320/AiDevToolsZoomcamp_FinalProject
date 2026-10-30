"""Meal logging (spec F12): check off, adjust, skip planned meals and add extra food.

* The planned meals of a date come from the athlete's active plan: the `MealDay` of that weekday,
  from the day the plan was created (same rule as the training template).
* A check-off is idempotent per (athlete, date, planned meal): the partial unique index decides
  under concurrency, and a repeat returns the existing log (F12.3).
* `eaten` stores the grams that were planned at that moment, so later plan edits never change the
  past (rule 7). Eaten totals count logged quantities only (F12.1).

Nothing here logs: meals, foods and dates are health data (spec §6.5).
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.engines.meal_macros import Per100g, meal_macros
from app.engines.nutrition_completion import nutrition_completion
from app.errors import ProblemError
from app.models import Food, MealDay, MealLog, MealLogItem, Plan, User
from app.models.plan import WEEKDAYS
from app.schemas import calendar as cal
from app.schemas import plans as plan_out
from app.schemas.foods import FoodSummary, Macros, MealItem
from app.schemas.logging import DayEnergyUpdate
from app.schemas.meal_log import MealLog as MealLogOut
from app.schemas.meal_log import MealLogInput, MealLogResult
from app.services import meal_plans
from app.services.clock import local_today
from app.services.foods import _visible


def _per_100g(food: Food) -> Per100g:
    return Per100g(
        food.kcal_per_100g, food.protein_g_per_100g, food.carbs_g_per_100g, food.fat_g_per_100g
    )


# ───────────── planned meals of a day ─────────────


def planned_meals(
    db: Session, user: User, day: dt.date
) -> tuple[MealDay | None, list[plan_out.PlannedMeal]]:
    """The meal day of the active plan for `day` and its planned meals (empty when none)."""
    plan = db.scalar(select(Plan).where(Plan.athlete_id == user.id, Plan.active.is_(True)))
    if plan is None or plan.created_at.astimezone(ZoneInfo(user.timezone)).date() > day:
        return None, []
    meal_day = db.scalar(
        select(MealDay)
        .where(MealDay.plan_id == plan.id, MealDay.weekday == WEEKDAYS[day.weekday()])
        .options(selectinload(MealDay.meals))
    )
    if meal_day is None:
        return None, []
    (view,) = meal_plans.meal_day_views(db, [meal_day], {})
    return meal_day, view.meals


# ───────────── logs → views ─────────────


def _log_views(db: Session, logs: Sequence[MealLog]) -> list[MealLogOut]:
    if not logs:
        return []
    rows = db.execute(
        select(MealLogItem, Food)
        .join(Food, Food.id == MealLogItem.food_id)
        .where(MealLogItem.meal_log_id.in_([log.id for log in logs]))
        .order_by(MealLogItem.position)
    ).all()
    by_log: dict[uuid.UUID, list[tuple[MealLogItem, Food]]] = {log.id: [] for log in logs}
    for item, food in rows:
        by_log[item.meal_log_id].append((item, food))
    views: list[MealLogOut] = []
    for log in logs:
        pairs = by_log[log.id]
        computed = meal_macros([(_per_100g(food), item.grams) for item, food in pairs])
        totals = computed.totals
        views.append(
            MealLogOut(
                id=log.id,
                date=log.date,
                planned_meal_id=log.planned_meal_id,
                status=log.status,  # type: ignore[arg-type]
                slot=log.slot,  # type: ignore[arg-type]
                items=[
                    MealItem(
                        food=FoodSummary(id=food.id, name=food.name, source=food.source),  # type: ignore[arg-type]
                        grams=item.grams,
                        kcal=m.kcal,
                        protein_g=m.protein_g,
                        carbs_g=m.carbs_g,
                        fat_g=m.fat_g,
                    )
                    for (item, food), m in zip(pairs, computed.items, strict=True)
                ],
                totals=Macros(
                    kcal=totals.kcal,
                    protein_g=totals.protein_g,
                    carbs_g=totals.carbs_g,
                    fat_g=totals.fat_g,
                ),
                logged_at=log.logged_at,
            )
        )
    return views


def day_logs(db: Session, athlete_id: uuid.UUID, day: dt.date) -> list[MealLogOut]:
    logs = db.scalars(
        select(MealLog)
        .where(MealLog.athlete_id == athlete_id, MealLog.date == day)
        .order_by(MealLog.logged_at, MealLog.id)
    ).all()
    return _log_views(db, logs)


def _sum(parts: Sequence[Macros]) -> cal.Macros:
    return cal.Macros(
        kcal=sum(p.kcal for p in parts),
        protein_g=round(sum(p.protein_g for p in parts), 1),
        carbs_g=round(sum(p.carbs_g for p in parts), 1),
        fat_g=round(sum(p.fat_g for p in parts), 1),
    )


@dataclass(frozen=True, slots=True)
class DayNutrition:
    planned: list[plan_out.PlannedMeal]
    logs: list[MealLogOut]
    eaten: cal.Macros  # logged quantities only (F12.1)
    planned_totals: cal.Macros
    completion: float | None  # F12.2


def day_nutrition(db: Session, user: User, day: dt.date) -> DayNutrition:
    """Planned meals, the day's logs, eaten totals (logged quantities only) and completion."""
    _, planned = planned_meals(db, user, day)
    logs = day_logs(db, user.id, day)
    eaten = _sum([log.totals for log in logs if log.status != "skipped"])
    by_planned = {log.planned_meal_id: log for log in logs if log.planned_meal_id}
    completion = nutrition_completion(
        [by_planned[p.id].status if p.id in by_planned else None for p in planned]
    )
    return DayNutrition(planned, logs, eaten, _sum([p.totals for p in planned]), completion.ratio)


def energy_update(db: Session, user: User, day: dt.date) -> DayEnergyUpdate:
    from app.services import training_log  # late: training_log builds on this module

    nutrition = day_nutrition(db, user, day)
    return DayEnergyUpdate(
        energy=training_log.day_energy(db, user, day, nutrition),
        nutrition_completion=nutrition.completion,
    )


# ───────────── writes ─────────────


def _items_for(
    db: Session, user: User, body: MealLogInput, planned: plan_out.PlannedMeal | None
) -> list[tuple[uuid.UUID, float]]:
    if body.status == "skipped":
        return []
    if body.status == "eaten":
        assert planned is not None  # noqa: S101 - validated by the caller
        return [(item.food.id, item.grams) for item in planned.items]
    assert body.items is not None  # noqa: S101 - schema guarantees it
    wanted = {item.food_id for item in body.items}
    visible = set(db.scalars(select(Food.id).where(Food.id.in_(wanted), _visible(Food, user))))
    if visible != wanted:
        raise ProblemError(404, "food_not_found", "One of the foods does not exist.")
    return [(item.food_id, item.grams) for item in body.items]


def _replace_items(db: Session, log: MealLog, items: Sequence[tuple[uuid.UUID, float]]) -> None:
    for old in db.scalars(select(MealLogItem).where(MealLogItem.meal_log_id == log.id)):
        db.delete(old)
    db.flush()
    for position, (food_id, grams) in enumerate(items):
        db.add(MealLogItem(meal_log_id=log.id, food_id=food_id, position=position, grams=grams))


def _existing(db: Session, user: User, body: MealLogInput) -> MealLog | None:
    return db.scalar(
        select(MealLog)
        .where(
            MealLog.athlete_id == user.id,
            MealLog.date == body.date,
            MealLog.planned_meal_id == body.planned_meal_id,
        )
        .with_for_update()
    )


def log_meal(
    db: Session, user: User, body: MealLogInput, now: dt.datetime
) -> tuple[MealLogResult, bool]:
    """Create or replace a meal log. Returns the result and whether a row was created."""
    if body.date > local_today(now, user.timezone):
        raise ProblemError(422, "date_in_future", "Meals cannot be logged for a future day.")
    planned: plan_out.PlannedMeal | None = None
    if body.planned_meal_id is not None:
        _, meals = planned_meals(db, user, body.date)
        planned = next((p for p in meals if p.id == body.planned_meal_id), None)
        if planned is None:
            raise ProblemError(404, "planned_meal_not_found", "That meal is not planned that day.")
    items = _items_for(db, user, body, planned)
    slot = body.slot if body.status == "extra" else planned.slot if planned else None

    created = False
    log = _existing(db, user, body) if body.planned_meal_id else None
    if log is None:
        log = MealLog(
            athlete_id=user.id,
            date=body.date,
            planned_meal_id=body.planned_meal_id,
            status=body.status,
            slot=slot,
            logged_at=now,
        )
        try:
            with db.begin_nested():
                db.add(log)
                db.flush()
            created = True
        except IntegrityError:  # a concurrent check-off won the race: behave as a repeat
            log = _existing(db, user, body)
            assert log is not None  # noqa: S101 - the unique index fired
        if created:
            _replace_items(db, log, items)
    # A repeated one-tap check-off keeps the snapshot taken the first time.
    repeat = log.status == body.status and body.status in ("eaten", "skipped")
    if not created and not repeat:
        log.status = body.status
        log.logged_at = now
        _replace_items(db, log, items)
    db.commit()
    view = _log_views(db, [log])[0]
    update = energy_update(db, user, body.date)
    result = MealLogResult(
        energy=update.energy, nutrition_completion=update.nutrition_completion, meal_log=view
    )
    return result, created and body.planned_meal_id is not None


def delete_meal_log(db: Session, user: User, meal_log_id: uuid.UUID) -> DayEnergyUpdate:
    log = db.get(MealLog, meal_log_id)
    if log is None or log.athlete_id != user.id:
        raise ProblemError(404, "meal_log_not_found", "That meal log does not exist.")
    day = log.date
    db.delete(log)
    db.commit()
    return energy_update(db, user, day)
