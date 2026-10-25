"""Suggestion request/response schemas (openapi.yaml tag Suggestions).

Only `progression` suggestions exist so far (calories and recalc arrive with F14); the response
keeps `payload` an open object whose shape is fixed by `kind` in the contract.
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.users import UserRef

SuggestionKind = Literal["progression", "calories", "recalc"]
SuggestionStatus = Literal["pending", "accepted", "rejected"]
SuggestionRule = Literal[
    "linear",
    "double",
    "deload",
    "bodyweight",
    "timed",
    "calibration",
    "adaptive_calories",
    "weight_change",
]


class Suggestion(ResponseModel):
    id: uuid.UUID
    athlete_id: uuid.UUID
    kind: SuggestionKind
    status: SuggestionStatus
    rule: SuggestionRule
    reason: str
    inputs: dict[str, Any]
    payload: dict[str, Any]
    created_at: dt.datetime
    decided_by: UserRef | None
    decided_at: dt.datetime | None


class SuggestionList(ResponseModel):
    items: list[Suggestion]
    weigh_in_hint: None = None


class SuggestionOverrides(RequestModel):
    target_weight_kg: Annotated[float, Field(ge=0, le=500)] | None = None
    reps_min: Annotated[int, Field(ge=1, le=100)] | None = None
    reps_max: Annotated[int, Field(ge=1, le=100)] | None = None
    target_seconds: Annotated[int, Field(ge=5, le=14400)] | None = None
    kcal: Annotated[int, Field(ge=1200, le=6000)] | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "SuggestionOverrides":
        if not self.model_fields_set:
            raise ValueError("overrides needs at least one property")
        return self


class AcceptSuggestionRequest(RequestModel):
    overrides: SuggestionOverrides | None = None
