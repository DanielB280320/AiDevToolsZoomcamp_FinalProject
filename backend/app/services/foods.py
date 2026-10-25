"""Food library and meals: search with keyset pagination and custom foods/meals (spec F6).

Visibility (F6, D47): seed and imported rows, the caller's own custom rows, and the custom rows of
the caller's active-link counterpart. Links arrive with #47; until then the last part is empty,
so a custom row is returned to its creator only (same as exercises).

Nothing here logs: food and meal names and brands are user content (spec section 6.5).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, and_, exists, func, not_, or_, select, tuple_
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.orm import Session

from app.engines.meal_macros import Per100g, meal_allergens, meal_diet_tags, meal_macros
from app.errors import ProblemError
from app.models import Food, Meal, MealItem, User
from app.schemas.foods import Food as FoodOut
from app.schemas.foods import FoodInput, FoodPage, FoodSummary, MealInput, MealPage
from app.schemas.foods import Macros as MacrosOut
from app.schemas.foods import Meal as MealOut
from app.schemas.foods import MealItem as MealItemOut
from app.schemas.users import UserRef
from app.services.paging import decode_cursor, encode_cursor, escape_like


def _owner_ref(owner: User | None) -> UserRef | None:
    if owner is None:
        return None
    return UserRef.model_validate(
        {"id": owner.id, "display_name": owner.display_name, "role": owner.role}
    )


def _owners(session: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, User]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {u.id: u for u in session.scalars(select(User).where(User.id.in_(wanted)))}


def _food_view(food: Food, owner: User | None) -> FoodOut:
    return FoodOut.model_validate(
        {
            "id": food.id,
            "name": food.name,
            "brand": food.brand,
            "kcal_per_100g": food.kcal_per_100g,
            "protein_g_per_100g": food.protein_g_per_100g,
            "carbs_g_per_100g": food.carbs_g_per_100g,
            "fat_g_per_100g": food.fat_g_per_100g,
            "diet_tags": food.diet_tags,
            "allergen_tags": food.allergen_tags,
            "source": food.source,
            "external_code": food.external_code,
            "owner": _owner_ref(owner),
        }
    )


def _visible(model: type[Food] | type[Meal], user: User) -> ColumnElement[bool]:
    return or_(model.owner_id.is_(None), model.owner_id == user.id)


def _name_filters(model: type[Food] | type[Meal], q: str | None) -> list[ColumnElement[bool]]:
    if q and q.strip():
        pattern = f"%{escape_like(q.strip().lower())}%"
        return [func.lower(model.name).like(pattern, escape="\\")]
    return []


def list_foods(
    session: Session,
    user: User,
    *,
    q: str | None,
    diet: str | None,
    exclude_allergens: Sequence[str],
    source: str | None,
    limit: int,
    cursor: str | None,
) -> FoodPage:
    statement = select(Food).where(_visible(Food, user), *_name_filters(Food, q))
    if diet is not None and diet != "omnivore":
        statement = statement.where(Food.diet_tags.contains([diet]))
    if exclude_allergens:
        statement = statement.where(
            not_(Food.allergen_tags.has_any(array(list(exclude_allergens))))
        )
    if source is not None:
        statement = statement.where(Food.source == source)
    if cursor:
        last_name, last_id = decode_cursor(cursor)
        statement = statement.where(
            tuple_(func.lower(Food.name), Food.id) > tuple_(last_name, last_id)
        )
    rows = list(
        session.scalars(statement.order_by(func.lower(Food.name), Food.id).limit(limit + 1))
    )
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].name, page[-1].id) if len(rows) > limit else None
    owners = _owners(session, {f.owner_id for f in page})
    return FoodPage(
        items=[_food_view(f, owners.get(f.owner_id) if f.owner_id else None) for f in page],
        next_cursor=next_cursor,
    )


def create_food(session: Session, user: User, body: FoodInput) -> FoodOut:
    """Create a custom food owned by `user`."""
    food = Food(
        owner_id=user.id,
        source="custom",
        name=body.name,
        brand=body.brand,
        kcal_per_100g=body.kcal_per_100g,
        protein_g_per_100g=body.protein_g_per_100g,
        carbs_g_per_100g=body.carbs_g_per_100g,
        fat_g_per_100g=body.fat_g_per_100g,
        diet_tags=sorted(body.diet_tags),
        allergen_tags=sorted(body.allergen_tags),
    )
    session.add(food)
    session.commit()
    session.refresh(food)
    return _food_view(food, user)


def _meal_view(meal: Meal, rows: Sequence[tuple[MealItem, Food]], owner: User | None) -> MealOut:
    ordered = sorted(rows, key=lambda row: row[0].position)
    computed = meal_macros(
        [
            (
                Per100g(
                    food.kcal_per_100g,
                    food.protein_g_per_100g,
                    food.carbs_g_per_100g,
                    food.fat_g_per_100g,
                ),
                item.grams,
            )
            for item, food in ordered
        ]
    )
    items = [
        MealItemOut(
            food=FoodSummary(id=food.id, name=food.name, source=food.source),  # type: ignore[arg-type]
            grams=item.grams,
            kcal=macros.kcal,
            protein_g=macros.protein_g,
            carbs_g=macros.carbs_g,
            fat_g=macros.fat_g,
        )
        for (item, food), macros in zip(ordered, computed.items, strict=True)
    ]
    totals = computed.totals
    return MealOut.model_validate(
        {
            "id": meal.id,
            "name": meal.name,
            "slots": meal.slots,
            "items": items,
            "totals": MacrosOut(
                kcal=totals.kcal,
                protein_g=totals.protein_g,
                carbs_g=totals.carbs_g,
                fat_g=totals.fat_g,
            ),
            "diet_tags": list(meal_diet_tags(food.diet_tags for _, food in ordered)),
            "allergen_tags": list(meal_allergens(food.allergen_tags for _, food in ordered)),
            "is_custom": meal.owner_id is not None,
            "owner": _owner_ref(owner),
        }
    )


def _meal_views(session: Session, meals: Sequence[Meal]) -> list[MealOut]:
    by_meal: dict[uuid.UUID, list[tuple[MealItem, Food]]] = {m.id: [] for m in meals}
    if meals:
        for item, food in session.execute(
            select(MealItem, Food)
            .join(Food, Food.id == MealItem.food_id)
            .where(MealItem.meal_id.in_(list(by_meal)))
        ):
            by_meal[item.meal_id].append((item, food))
    owners = _owners(session, {m.owner_id for m in meals})
    return [
        _meal_view(m, by_meal[m.id], owners.get(m.owner_id) if m.owner_id else None) for m in meals
    ]


def list_meals(
    session: Session,
    user: User,
    *,
    q: str | None,
    slot: str | None,
    diet: str | None,
    exclude_allergens: Sequence[str],
    limit: int,
    cursor: str | None,
) -> MealPage:
    statement = select(Meal).where(_visible(Meal, user), *_name_filters(Meal, q))
    if slot is not None:
        statement = statement.where(Meal.slots.contains([slot]))
    if diet is not None and diet != "omnivore":
        # A meal suits the diet when none of its foods lacks the tag (derived, F6.5).
        statement = statement.where(
            not_(
                exists().where(
                    and_(
                        MealItem.meal_id == Meal.id,
                        Food.id == MealItem.food_id,
                        not_(Food.diet_tags.contains([diet])),
                    )
                )
            )
        )
    if exclude_allergens:
        statement = statement.where(
            not_(
                exists().where(
                    and_(
                        MealItem.meal_id == Meal.id,
                        Food.id == MealItem.food_id,
                        Food.allergen_tags.has_any(array(list(exclude_allergens))),
                    )
                )
            )
        )
    if cursor:
        last_name, last_id = decode_cursor(cursor)
        statement = statement.where(
            tuple_(func.lower(Meal.name), Meal.id) > tuple_(last_name, last_id)
        )
    rows = list(
        session.scalars(statement.order_by(func.lower(Meal.name), Meal.id).limit(limit + 1))
    )
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].name, page[-1].id) if len(rows) > limit else None
    return MealPage(items=_meal_views(session, page), next_cursor=next_cursor)


def create_meal(session: Session, user: User, body: MealInput) -> MealOut:
    """Create a custom meal. 404 `food_not_found` when any food does not exist or is not visible
    to the caller (the two cases are indistinguishable, so ids cannot be probed)."""
    wanted = {item.food_id for item in body.items}
    found = set(session.scalars(select(Food.id).where(Food.id.in_(wanted), _visible(Food, user))))
    if found != wanted:
        raise ProblemError(404, "food_not_found", "One of the foods does not exist.")
    meal = Meal(owner_id=user.id, source="custom", name=body.name, slots=sorted(body.slots))
    session.add(meal)
    session.flush()
    for position, item in enumerate(body.items):
        session.add(
            MealItem(meal_id=meal.id, food_id=item.food_id, position=position, grams=item.grams)
        )
    session.commit()
    session.refresh(meal)
    return _meal_views(session, [meal])[0]
