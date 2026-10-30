"""Meal logging (spec F12): check off, adjust, skip planned meals and add extra food.

* The planned meals of a date come from the athlete's active plan: the `MealDay` of that weekday,
  from the day the plan was created (same rule as the training template).
* A check-off is idempotent per (athlete, date, meal key; D73): the partial unique index decides
  under concurrency, and a repeat returns the existing log (F12.3).
* `eaten` stores the grams that were planned at that moment, so later plan edits never change the
  past (rule 7). Eaten totals count logged quantities only (F12.1).

Nothing here logs: meals, foods and dates are health data (spec §6.5).
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

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
from app.services.calendar import utc_midnight_after
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
    """The meal day and planned meals that apply on `day`: the latest plan version created on or
    before the end of that day that has a meal day for its weekday. A newer version never
    rewrites an earlier day (rule 7), and a version without meal days (a plan edit that did not
    carry them over) does not hide the meal plan."""
    end = utc_midnight_after(day, user.timezone)
    meal_day = db.scalar(
        select(MealDay)
        .join(Plan, Plan.id == MealDay.plan_id)
        .where(
            Plan.athlete_id == user.id,
            Plan.created_at < end,
            MealDay.weekday == WEEKDAYS[day.weekday()],
        )
        .order_by(Plan.version.desc())
        .limit(1)
        .options(selectinload(MealDay.meals))
    )
    if meal_day is None:
        return None, []
    (view,) = meal_plans.meal_day_views(db, [meal_day], {})
    return meal_day, view.meals


def meal_keys(meal_day: MealDay | None) -> dict[uuid.UUID, uuid.UUID]:
    """`planned_meal.meal_key` by planned meal id: the identity that survives new plan versions
    (D73)."""
    if meal_day is None:
        return {}
    return {m.id: m.meal_key for m in meal_day.meals if m.meal_key is not None}


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


def day_logs(
    db: Session, athlete_id: uuid.UUID, day: dt.date
) -> tuple[list[MealLogOut], dict[uuid.UUID, uuid.UUID]]:
    """The day's logs and, for planned-meal logs, their meal key by log id."""
    logs = db.scalars(
        select(MealLog)
        .where(MealLog.athlete_id == athlete_id, MealLog.date == day)
        .order_by(MealLog.logged_at, MealLog.id)
    ).all()
    keys = {
        log.id: log.meal_key
        for log in logs
        if log.planned_meal_id is not None and log.meal_key is not None
    }
    return _log_views(db, logs), keys


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
    meals: list[tuple[plan_out.PlannedMeal, MealLogOut | None]]  # planned meal and its log
    extra_logs: list[MealLogOut]  # extra food, plus planned-meal logs matching no planned meal
    eaten: cal.Macros  # logged quantities only (F12.1)
    planned_totals: cal.Macros
    completion: float | None  # F12.2


def day_nutrition(db: Session, user: User, day: dt.date) -> DayNutrition:
    """Planned meals with their logs, the other logs, eaten totals and completion."""
    meal_day, planned = planned_meals(db, user, day)
    plan_keys = meal_keys(meal_day)
    logs, keys = day_logs(db, user.id, day)
    by_key = {keys[log.id]: log for log in logs if log.id in keys}
    matched: set[uuid.UUID] = set()
    meals: list[tuple[plan_out.PlannedMeal, MealLogOut | None]] = []
    for meal in planned:
        log = by_key.get(plan_keys[meal.id]) if meal.id in plan_keys else None
        if log is not None:
            matched.add(log.id)
            log = log.model_copy(update={"planned_meal_id": meal.id})
        meals.append((meal, log))
    # Every log that counts in `eaten` stays visible and undoable, even when the plan no longer
    # has a meal for it.
    extra_logs = [log for log in logs if log.id not in matched]
    eaten = _sum([log.totals for log in logs if log.status != "skipped"])
    completion = nutrition_completion([log.status if log else None for _, log in meals])
    return DayNutrition(
        planned, meals, extra_logs, eaten, _sum([p.totals for p in planned]), completion.ratio
    )


def range_totals(
    db: Session, user: User, start: dt.date, end: dt.date
) -> dict[dt.date, tuple[cal.Macros, cal.Macros]]:
    """(eaten, planned) macro totals for every day in `start..end` in a fixed number of queries.

    Same rules as `day_nutrition` (logged quantities only; the plan version that applies on each
    day), used by the calendar range so a 6-week grid stays fast (F9.4)."""
    logs = db.scalars(
        select(MealLog).where(
            MealLog.athlete_id == user.id, MealLog.date >= start, MealLog.date <= end
        )
    ).all()
    eaten_parts: dict[dt.date, list[Macros]] = {}
    for log_view in _log_views(db, logs):
        if log_view.status != "skipped":
            eaten_parts.setdefault(log_view.date, []).append(log_view.totals)
    candidates = db.execute(
        select(MealDay.id, MealDay.weekday, Plan.version, Plan.created_at)
        .join(Plan, Plan.id == MealDay.plan_id)
        .where(Plan.athlete_id == user.id)
        .order_by(Plan.version.desc())
    ).all()
    chosen: dict[dt.date, uuid.UUID] = {}
    for offset in range((end - start).days + 1):
        day = start + dt.timedelta(days=offset)
        cutoff = utc_midnight_after(day, user.timezone)
        for meal_day_id, weekday, _version, created_at in candidates:
            if weekday == WEEKDAYS[day.weekday()] and created_at < cutoff:
                chosen[day] = meal_day_id
                break
    planned_by_id: dict[uuid.UUID, cal.Macros] = {}
    if chosen:
        meal_days = db.scalars(
            select(MealDay)
            .where(MealDay.id.in_(set(chosen.values())))
            .options(selectinload(MealDay.meals))
        ).all()
        for day_view in meal_plans.meal_day_views(db, meal_days, {}):
            planned_by_id[day_view.id] = _sum([m.totals for m in day_view.meals])
    result: dict[dt.date, tuple[cal.Macros, cal.Macros]] = {}
    for offset in range((end - start).days + 1):
        day = start + dt.timedelta(days=offset)
        planned = planned_by_id[chosen[day]] if day in chosen else cal.Macros()
        result[day] = (_sum(eaten_parts.get(day, [])), planned)
    return result


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


def _existing(db: Session, user: User, body: MealLogInput, key: uuid.UUID) -> MealLog | None:
    return db.scalar(
        select(MealLog)
        .where(
            MealLog.athlete_id == user.id,
            MealLog.date == body.date,
            MealLog.meal_key == key,
            MealLog.planned_meal_id.is_not(None),
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
    key: uuid.UUID | None = None
    slot_index: int | None = None
    if body.planned_meal_id is not None:
        meal_day, meals = planned_meals(db, user, body.date)
        planned = next((p for p in meals if p.id == body.planned_meal_id), None)
        if planned is not None:
            # Position among the slot's meals, still written for the previous release (D73).
            slot_index = sum(1 for p in meals[: meals.index(planned)] if p.slot == planned.slot)
        key = meal_keys(meal_day).get(body.planned_meal_id)
        if planned is None or key is None:
            raise ProblemError(404, "planned_meal_not_found", "That meal is not planned that day.")
    items = _items_for(db, user, body, planned)
    slot = body.slot if body.status == "extra" else planned.slot if planned else None

    created = False
    log = _existing(db, user, body, key) if key else None
    if log is None:
        log = MealLog(
            athlete_id=user.id,
            date=body.date,
            planned_meal_id=body.planned_meal_id,
            status=body.status,
            slot=slot,
            meal_key=key,
            slot_index=slot_index,
            logged_at=now,
        )
        try:
            with db.begin_nested():
                db.add(log)
                db.flush()
            created = True
        except IntegrityError:  # a concurrent check-off won the race: behave as a repeat
            assert key is not None  # noqa: S101 - only planned meals can collide
            log = _existing(db, user, body, key)
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
    if planned is not None:
        view = view.model_copy(update={"planned_meal_id": planned.id})
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
