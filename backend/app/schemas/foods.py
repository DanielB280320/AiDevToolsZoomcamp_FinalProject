"""Food and meal schemas (openapi.yaml: `FoodInput`, `Food`, `FoodPage`, `MealInput`, `Meal`)."""

import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints
from pydantic_core import PydanticCustomError

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.users import UserRef

DietTag = Literal["vegetarian", "vegan", "pescatarian"]
Allergen = Literal["gluten", "lactose", "nuts", "eggs", "soy", "shellfish", "fish"]
FoodSource = Literal["seed", "custom", "openfoodfacts"]
MealSlot = Literal["breakfast", "lunch", "dinner", "snack"]


def _unique(values: list[str]) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError("Values must be unique.")
    return values


Kcal100 = Annotated[float, Field(ge=0, le=900, allow_inf_nan=False)]
Gram100 = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class FoodInput(RequestModel):
    name: Name
    brand: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    kcal_per_100g: Kcal100
    protein_g_per_100g: Gram100
    carbs_g_per_100g: Gram100
    fat_g_per_100g: Gram100
    diet_tags: Annotated[list[DietTag], AfterValidator(_unique)] = Field(default_factory=list)
    allergen_tags: Annotated[list[Allergen], AfterValidator(_unique)] = Field(default_factory=list)


class Food(ResponseModel):
    id: uuid.UUID
    name: str
    brand: str | None
    kcal_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
    diet_tags: list[DietTag]
    allergen_tags: list[Allergen]
    source: FoodSource
    external_code: str | None
    owner: UserRef | None


class FoodPage(ResponseModel):
    items: list[Food]
    next_cursor: str | None


class FoodSummary(ResponseModel):
    id: uuid.UUID
    name: str
    source: FoodSource


def _grams_to_tenth(value: float) -> float:
    """Grams are stored to 0.1 g; a positive amount that rounds to zero is invalid."""
    rounded = round(value, 1)
    if rounded <= 0:
        raise PydanticCustomError("out_of_range", "Use at least 0.1 g.")
    return rounded


class FoodGrams(RequestModel):
    food_id: uuid.UUID
    grams: Annotated[
        float, Field(gt=0, le=2000, allow_inf_nan=False), AfterValidator(_grams_to_tenth)
    ]


class MealInput(RequestModel):
    name: Name
    slots: Annotated[list[MealSlot], Field(min_length=1), AfterValidator(_unique)]
    items: Annotated[list[FoodGrams], Field(min_length=1, max_length=30)]


class Macros(ResponseModel):
    kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float


class MealItem(Macros):
    food: FoodSummary
    grams: float


class Meal(ResponseModel):
    id: uuid.UUID
    name: str
    slots: list[MealSlot]
    items: list[MealItem]
    totals: Macros
    diet_tags: list[DietTag]
    allergen_tags: list[Allergen]
    is_custom: bool
    owner: UserRef | None


class MealPage(ResponseModel):
    items: list[Meal]
    next_cursor: str | None


class OffProduct(ResponseModel):
    code: str
    name: str
    brand: str | None
    kcal_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
    imported_food_id: uuid.UUID | None


class OffSearchResult(ResponseModel):
    available: bool
    unavailable_reason: Literal["disabled", "timeout", "upstream_error"] | None
    message: str | None
    items: list[OffProduct]


class FoodImportRequest(RequestModel):
    code: Annotated[str, StringConstraints(pattern=r"^[0-9]{4,14}$")]
