"""Meal swap suggestions (D86): resolve the planned meal, run the pure engine, shape the answer.

Read-only: applying a swap goes through `PUT /plan/meals` (a replacement gets a new `meal_key`,
D73). Nothing here logs: meals and plans are health data (spec §6.5).
"""

import datetime as dt
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.engines.meal_swap import SwapRequest, suggest_swaps
from app.errors import ProblemError
from app.models import AthleteProfile, Meal, MealDay, Plan, User
from app.models.plan import WEEKDAYS
from app.schemas import plans as out
from app.schemas.foods import Macros
from app.services import meal_plans
from app.services.clock import local_today


def swaps(
    db: Session,
    athlete: User,
    meal_key: uuid.UUID,
    day: dt.date | None,
    now: dt.datetime,
) -> out.MealSwapList:
    """Up to 3 alternatives for the planned meal `meal_key` of the active plan.

    `day` (optional) is the calendar date the athlete is editing; it must be today or later in
    their time zone (F8.1, `422 past_day`) and fall on the meal's weekday (`422 wrong_weekday`).
    Without it the meal is taken as the next occurrence of its weekday, which is never past.
    """
    plan = db.scalar(
        select(Plan)
        .where(Plan.athlete_id == athlete.id, Plan.active.is_(True))
        .options(selectinload(Plan.meal_days).selectinload(MealDay.meals))
    )
    profile = db.get(AthleteProfile, athlete.id)
    if plan is None or profile is None:
        raise ProblemError(
            404, "not_onboarded", "There is no plan yet. Complete onboarding to get one."
        )
    found = next(((d, m) for d in plan.meal_days for m in d.meals if m.meal_key == meal_key), None)
    if found is None:
        raise ProblemError(404, "meal_not_found", "This meal is not in the active plan.")
    meal_day, planned = found
    if day is not None:
        if day < local_today(now, athlete.timezone):
            raise ProblemError(
                422, "past_day", "Meals of past days cannot be changed (the past never changes)."
            )
        if WEEKDAYS[day.weekday()] != meal_day.weekday:
            raise ProblemError(
                422, "wrong_weekday", "The date is not on the weekday of this planned meal."
            )
    view = meal_plans.meal_day_views(db, [meal_day], {})[0]
    planned_view = next(m for m in view.meals if m.id == planned.id)
    week_uses = Counter(str(m.meal_id) for d in plan.meal_days for m in d.meals)
    result = suggest_swaps(
        SwapRequest(
            slot=planned.slot,
            planned_kcal=float(planned_view.totals.kcal),
            diet=profile.diet,
            allergies=tuple(profile.allergies),
            day_meal_ids=tuple(str(m.meal_id) for m in meal_day.meals),
            week_uses=week_uses,
        ),
        meal_plans.candidates(db, athlete.id),
    )
    ids = [uuid.UUID(a.meal_id) for a in result.alternatives]
    names = {m.id: m.name for m in db.scalars(select(Meal).where(Meal.id.in_(ids)))} if ids else {}
    return out.MealSwapList(
        meal_key=meal_key,
        alternatives=[
            out.MealSwap(
                meal_id=uuid.UUID(a.meal_id),
                name=names[uuid.UUID(a.meal_id)],
                portion_factor=a.portion_factor,
                items=meal_plans.scaled_items(
                    meal_plans.meal_rows(db, uuid.UUID(a.meal_id)), a.portion_factor
                )[0],
                totals=Macros(kcal=a.kcal, protein_g=a.protein_g, carbs_g=a.carbs_g, fat_g=a.fat_g),
            )
            for a in result.alternatives
        ],
        reason=result.reason,
    )
