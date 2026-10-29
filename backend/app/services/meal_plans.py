"""Meal plan generation inputs and views (spec F7, F8).

`candidates` turns the meals an athlete may use (seed meals and their own custom ones) into the
plain data the pure F7 engine needs; `generate` runs it; `meal_day_views` renders stored
`MealDay`/`PlannedMeal` rows with their foods scaled by the portion factor.

Nothing here logs: meals and plans are health data (spec §6.5).
"""

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.engines.meal_macros import (
    Per100g,
    meal_allergens,
    meal_diet_tags,
    meal_macros,
)
from app.engines.meal_plan import (
    GeneratedMealPlan,
    MealCandidate,
    MealPlanRequest,
    generate_meal_plan,
    plan_seed,
)
from app.models import Food, Meal, MealDay, MealItem, PlannedMeal, User
from app.schemas import plans as out
from app.schemas.foods import FoodSummary, Macros
from app.schemas.foods import MealItem as MealItemOut
from app.schemas.users import UserRef


def _per_100g(food: Food) -> Per100g:
    return Per100g(
        food.kcal_per_100g,
        food.protein_g_per_100g,
        food.carbs_g_per_100g,
        food.fat_g_per_100g,
    )


def candidates(session: Session, athlete_id: uuid.UUID) -> list[MealCandidate]:
    """Seed meals and the athlete's own meals, as engine input (macros at portion factor 1)."""
    meals = list(
        session.scalars(
            select(Meal).where(or_(Meal.owner_id.is_(None), Meal.owner_id == athlete_id))
        )
    )
    rows: dict[uuid.UUID, list[tuple[MealItem, Food]]] = {m.id: [] for m in meals}
    if meals:
        for item, food in session.execute(
            select(MealItem, Food)
            .join(Food, Food.id == MealItem.food_id)
            .where(MealItem.meal_id.in_(list(rows)))
        ):
            rows[item.meal_id].append((item, food))
    result: list[MealCandidate] = []
    for meal in meals:
        pairs = rows[meal.id]
        if not pairs:
            continue
        totals = meal_macros([(_per_100g(food), item.grams) for item, food in pairs]).totals
        result.append(
            MealCandidate(
                id=str(meal.id),
                slots=tuple(meal.slots),
                diet_tags=meal_diet_tags(food.diet_tags for _, food in pairs),
                allergens=meal_allergens(food.allergen_tags for _, food in pairs),
                kcal=totals.kcal,
                protein_g=totals.protein_g,
            )
        )
    return result


def generate(
    session: Session,
    *,
    athlete_id: uuid.UUID,
    today: dt.date,
    kcal: float,
    protein_g: float,
    meals_per_day: int,
    diet: str,
    allergies: Sequence[str],
) -> GeneratedMealPlan:
    """Run the F7 engine for the athlete; the seed is `user_id + ISO week` of the local `today`."""
    iso = today.isocalendar()
    return generate_meal_plan(
        MealPlanRequest(
            kcal=kcal,
            protein_g=protein_g,
            meals_per_day=meals_per_day,
            diet=diet,
            allergies=tuple(allergies),
            seed=plan_seed(athlete_id.int, iso.year, iso.week),
        ),
        candidates(session, athlete_id),
    )


# ───────────── views ─────────────


def _macros(kcal: int, protein: float, carbs: float, fat: float) -> Macros:
    return Macros(kcal=kcal, protein_g=protein, carbs_g=carbs, fat_g=fat)


def meal_day_views(
    session: Session, days: Sequence[MealDay], users: dict[uuid.UUID, User]
) -> list[out.MealDay]:
    """Stored meal days with foods scaled by each planned meal's portion factor."""
    meal_ids = {p.meal_id for d in days for p in d.meals}
    meals = {m.id: m for m in session.scalars(select(Meal).where(Meal.id.in_(meal_ids)))}
    foods: dict[uuid.UUID, list[tuple[MealItem, Food]]] = {i: [] for i in meal_ids}
    if meal_ids:
        for item, food in session.execute(
            select(MealItem, Food)
            .join(Food, Food.id == MealItem.food_id)
            .where(MealItem.meal_id.in_(meal_ids))
            .order_by(MealItem.position)
        ):
            foods[item.meal_id].append((item, food))
    return [_day_view(day, meals, foods, users) for day in days]


def _planned_view(
    planned: PlannedMeal, meal: Meal, rows: Sequence[tuple[MealItem, Food]]
) -> out.PlannedMeal:
    scaled = [(food, round(item.grams * planned.portion_factor, 1)) for item, food in rows]
    computed = meal_macros([(_per_100g(food), grams) for food, grams in scaled])
    items = [
        MealItemOut(
            food=FoodSummary(id=food.id, name=food.name, source=food.source),  # type: ignore[arg-type]
            grams=grams,
            kcal=macros.kcal,
            protein_g=macros.protein_g,
            carbs_g=macros.carbs_g,
            fat_g=macros.fat_g,
        )
        for (food, grams), macros in zip(scaled, computed.items, strict=True)
    ]
    totals = computed.totals
    return out.PlannedMeal(
        id=planned.id,
        slot=planned.slot,  # type: ignore[arg-type]
        order=planned.position,
        meal=out.MealSummary(id=meal.id, name=meal.name, slots=meal.slots),  # type: ignore[arg-type]
        portion_factor=planned.portion_factor,
        items=items,
        totals=_macros(totals.kcal, totals.protein_g, totals.carbs_g, totals.fat_g),
    )


def _day_view(
    day: MealDay,
    meals: dict[uuid.UUID, Meal],
    foods: dict[uuid.UUID, list[tuple[MealItem, Food]]],
    users: dict[uuid.UUID, User],
) -> out.MealDay:
    planned = [_planned_view(p, meals[p.meal_id], foods[p.meal_id]) for p in day.meals]
    editor = users.get(day.edited_by) if day.edited_by else None
    return out.MealDay(
        id=day.id,
        weekday=day.weekday,  # type: ignore[arg-type]
        meals=planned,
        totals=_macros(
            sum(p.totals.kcal for p in planned),
            round(sum(p.totals.protein_g for p in planned), 1),
            round(sum(p.totals.carbs_g for p in planned), 1),
            round(sum(p.totals.fat_g for p in planned), 1),
        ),
        warning=day.warning,
        edited_by=(
            UserRef.model_validate(
                {"id": editor.id, "display_name": editor.display_name, "role": editor.role}
            )
            if editor
            else None
        ),
    )


__all__ = ["candidates", "generate", "meal_day_views"]
