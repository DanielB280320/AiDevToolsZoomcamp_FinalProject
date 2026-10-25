"""`GET/POST /foods` and `GET/POST /meals` (openapi.yaml, tag Catalog)."""

from typing import Annotated, get_args

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, SessionDep
from app.errors import ProblemError
from app.schemas.athlete import Diet
from app.schemas.base import NoNul
from app.schemas.foods import (
    Allergen,
    Food,
    FoodInput,
    FoodPage,
    FoodSource,
    Meal,
    MealInput,
    MealPage,
    MealSlot,
)
from app.schemas.problem import FieldError, Problem
from app.services import foods

foods_router = APIRouter(prefix="/foods", tags=["Catalog"])
meals_router = APIRouter(prefix="/meals", tags=["Catalog"])

_PROBLEM = {"model": Problem}
_ALLERGENS = frozenset(get_args(Allergen))


def _parse_allergens(raw: str | None) -> list[str]:
    """`exclude_allergens=gluten,nuts` -> ['gluten', 'nuts']; unknown values are a 400."""
    if not raw:
        return []
    values = [v.strip() for v in raw.split(",") if v.strip()]
    if any(v not in _ALLERGENS for v in values) or len(set(values)) != len(values):
        raise ProblemError(
            400,
            "bad_request",
            "One or more parameters are invalid.",
            errors=[
                FieldError(
                    field="exclude_allergens",
                    code="invalid_choice",
                    message="Use distinct allergens separated by commas.",
                )
            ],
        )
    return values


Q = Annotated[str | None, Query(max_length=100), NoNul]
Allergens = Annotated[str | None, Query(max_length=100), NoNul]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, NoNul]


@foods_router.get(
    "",
    operation_id="listFoods",
    response_model=FoodPage,
    responses={400: _PROBLEM, 401: _PROBLEM},
)
def list_foods(
    user: CurrentUser,
    session: SessionDep,
    q: Q = None,
    diet: Diet | None = None,
    exclude_allergens: Allergens = None,
    source: FoodSource | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> FoodPage:
    """Seed, imported and visible custom foods, ordered by name; filters combine with AND."""
    return foods.list_foods(
        session,
        user,
        q=q,
        diet=diet,
        exclude_allergens=_parse_allergens(exclude_allergens),
        source=source,
        limit=limit,
        cursor=cursor,
    )


@foods_router.post(
    "",
    operation_id="createFood",
    response_model=Food,
    status_code=201,
    responses={400: _PROBLEM, 401: _PROBLEM, 422: _PROBLEM},
)
def create_food(body: FoodInput, user: CurrentUser, session: SessionDep) -> Food:
    """Create a custom food owned by the caller."""
    return foods.create_food(session, user, body)


@meals_router.get(
    "",
    operation_id="listMeals",
    response_model=MealPage,
    responses={400: _PROBLEM, 401: _PROBLEM},
)
def list_meals(
    user: CurrentUser,
    session: SessionDep,
    q: Q = None,
    slot: MealSlot | None = None,
    diet: Diet | None = None,
    exclude_allergens: Allergens = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> MealPage:
    """Seed and visible custom meals with computed macros, ordered by name."""
    return foods.list_meals(
        session,
        user,
        q=q,
        slot=slot,
        diet=diet,
        exclude_allergens=_parse_allergens(exclude_allergens),
        limit=limit,
        cursor=cursor,
    )


@meals_router.post(
    "",
    operation_id="createMeal",
    response_model=Meal,
    status_code=201,
    responses={400: _PROBLEM, 401: _PROBLEM, 404: _PROBLEM, 422: _PROBLEM},
)
def create_meal(body: MealInput, user: CurrentUser, session: SessionDep) -> Meal:
    """Create a custom meal from foods and grams."""
    return foods.create_meal(session, user, body)
