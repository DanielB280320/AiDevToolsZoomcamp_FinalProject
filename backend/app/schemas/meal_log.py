"""Meal log request/response schemas (openapi.yaml `MealLogInput`, `MealLog`, `MealLogResult`)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.foods import FoodGrams, Macros, MealItem, MealSlot
from app.schemas.logging import DayEnergyUpdate

MealLogStatus = Literal["eaten", "adjusted", "skipped", "extra"]


class MealLogInput(RequestModel):
    date: dt.date
    planned_meal_id: uuid.UUID | None
    status: MealLogStatus
    slot: MealSlot | None = None
    items: Annotated[list[FoodGrams], Field(min_length=1, max_length=30)] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "MealLogInput":
        if self.status == "extra":
            if self.planned_meal_id is not None:
                raise ValueError("Extra food has no planned meal.")
            if self.items is None:
                raise ValueError("Extra food needs items.")
        else:
            if self.planned_meal_id is None:
                raise ValueError("A planned meal id is required.")
            if self.slot is not None:
                raise ValueError("Only extra food has a slot.")
            if self.status == "adjusted" and self.items is None:
                raise ValueError("An adjusted meal needs items.")
            if self.status in ("eaten", "skipped") and self.items is not None:
                raise ValueError("Only adjusted meals and extra food take items.")
        return self


class MealLog(ResponseModel):
    id: uuid.UUID
    date: dt.date
    planned_meal_id: uuid.UUID | None
    status: MealLogStatus
    slot: MealSlot | None
    items: list[MealItem]
    totals: Macros
    logged_at: dt.datetime


class MealLogResult(DayEnergyUpdate):
    meal_log: MealLog
