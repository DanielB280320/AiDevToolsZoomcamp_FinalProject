"""Rescale meal portions when the athlete's targets change (spec D74).

One shared service for the three paths that change targets: accepting a `recalc` suggestion,
editing the profile (D46) and accepting a `calories` suggestion (F14). The rescale is a new plan
version created now: it applies from today on (a day uses the latest version created before its
end), while earlier days keep the version they were planned with (rule 7). Every `meal_id` and
`meal_key` (D73) is carried forward and only `portion_factor` changes, so logs stay attached.

Nothing here logs: plans, kcal and portions are health data (spec §6.5).
"""

import datetime as dt
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.engines.meal_rescale import rescale_portions
from app.models import MealDay, Plan, TrainingDay, User
from app.services import meal_plans, plan_edit
from app.services.plans import NewMealDay, NewPlannedMeal, create_plan_version

RescaleReason = Literal["recalc", "profile", "calories"]


def rescale_future_meals(
    db: Session,
    *,
    athlete: User,
    author: User,
    new_kcal: float,
    now: dt.datetime,
    reason: RescaleReason,
) -> Plan | None:
    """Store the athlete's meal portions rescaled to `new_kcal` per day as a new plan version.

    Returns the new version, or `None` when there is nothing to do: no active plan, a plan
    without meal days, or portions that already match. Does not commit. `author` is the acting
    user (the athlete, or a linked coach accepting a suggestion); the plan `source` is kept."""
    db.execute(select(User.id).where(User.id == athlete.id).with_for_update()).one()
    old = db.scalar(
        select(Plan)
        .where(Plan.athlete_id == athlete.id, Plan.active.is_(True))
        .options(
            selectinload(Plan.training_days).selectinload(TrainingDay.exercises),
            selectinload(Plan.meal_days).selectinload(MealDay.meals),
        )
    )
    if old is None or not old.meal_days:
        return None
    ordered = sorted(old.meal_days, key=lambda d: d.position)
    views = {v.id: v for v in meal_plans.meal_day_views(db, ordered, {})}
    new_days: list[NewMealDay] = []
    changed = 0
    for day in ordered:
        meals = sorted(day.meals, key=lambda m: m.position)
        planned = {p.id: p for p in views[day.id].meals}
        factors = [float(m.portion_factor) for m in meals]
        result = rescale_portions(factors, [planned[m.id].totals.kcal for m in meals], new_kcal)
        if list(result.factors) != factors:
            changed += 1
        new_days.append(
            NewMealDay(
                weekday=day.weekday,
                warning=day.warning,
                edited_by=day.edited_by,
                meals=[
                    NewPlannedMeal(m.slot, m.meal_id, factor, m.meal_key)
                    for m, factor in zip(meals, result.factors, strict=True)
                ],
            )
        )
    if changed == 0:
        return None
    new = create_plan_version(
        db,
        athlete_id=athlete.id,
        author_id=author.id,
        source=old.source,
        days=plan_edit._carry_days(old),
        meal_days=new_days,
        now=now,
        revision=old.revision + 1,
        change={"kind": "portions_rescaled", "reason": reason, "days": changed},
    )
    plan_edit._finish(
        db,
        athlete=athlete,
        author=author,
        old=old,
        new=new,
        now=now,
        planned_map=plan_edit._planned_map(old, new),
    )
    return new


__all__ = ["rescale_future_meals"]
