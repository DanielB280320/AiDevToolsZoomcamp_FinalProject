"""`GET/POST /foods` and `GET/POST /meals` (openapi.yaml, tag Catalog)."""

from typing import Annotated, get_args

from fastapi import APIRouter, Query, Request, Response

from app.dependencies import CurrentUser, SessionDep, TelemetryDep
from app.errors import ProblemError
from app.schemas.athlete import Diet
from app.schemas.base import NoNul
from app.schemas.foods import (
    Allergen,
    Food,
    FoodImportRequest,
    FoodInput,
    FoodPage,
    FoodSource,
    Meal,
    MealInput,
    MealPage,
    MealSlot,
    OffSearchResult,
)
from app.schemas.problem import FieldError, Problem
from app.services import food_import, foods
from app.services.clock import ClockDep
from app.services.flags import FlagsDep
from app.services.off import OffClient

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


SearchTerm = Annotated[str, Query(min_length=2, max_length=100), NoNul]


def _off(request: Request) -> OffClient:
    client: OffClient = request.app.state.off
    return client


@foods_router.get(
    "/search",
    operation_id="searchOpenFoodFacts",
    response_model=OffSearchResult,
    responses={400: _PROBLEM, 401: _PROBLEM},
)
def search_open_food_facts(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    flags: FlagsDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
    q: SearchTerm,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> OffSearchResult:
    """Open Food Facts proxy; a disabled flag or a failing upstream gives `available: false`."""
    return food_import.search(
        session,
        _off(request),
        telemetry.metrics,
        enabled=flags.off_search_enabled,
        query=q,
        limit=limit,
        now=clock.now(),
    )


@foods_router.post(
    "/import",
    operation_id="importOpenFoodFactsFood",
    response_model=Food,
    status_code=201,
    responses={
        200: {"model": Food},
        400: _PROBLEM,
        401: _PROBLEM,
        404: _PROBLEM,
        422: _PROBLEM,
        503: _PROBLEM,
    },
)
def import_open_food_facts_food(
    body: FoodImportRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: SessionDep,
    flags: FlagsDep,
    clock: ClockDep,
) -> Food:
    """Copy a product into `Food` (unique on its code): 201 when new, 200 when already there."""
    food, created = food_import.import_product(
        session, _off(request), enabled=flags.off_search_enabled, code=body.code, now=clock.now()
    )
    if not created:
        response.status_code = 200
    return food


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
