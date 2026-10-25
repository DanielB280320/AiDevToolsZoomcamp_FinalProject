"""Logging request/response schemas (openapi.yaml tag Logging: sets, finish, activities)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.calendar import EnergyBalance, Session
from app.schemas.plans import ExerciseSummary
from app.schemas.suggestions import Suggestion


class SetLogInput(RequestModel):
    exercise_id: uuid.UUID
    planned_exercise_id: uuid.UUID | None = None
    set_no: Annotated[int, Field(ge=1, le=30)]
    as_planned: bool = False
    skipped: bool = False
    reps: Annotated[int, Field(ge=0, le=1000)] | None = None
    weight_kg: Annotated[float, Field(ge=0, le=1000)] | None = None
    seconds: Annotated[int, Field(ge=0, le=86400)] | None = None
    distance_m: Annotated[float, Field(ge=0, le=1000000)] | None = None


class FinishSessionRequest(RequestModel):
    finished_at: dt.datetime | None = None


class FinishSessionResult(ResponseModel):
    session: Session
    suggestions: list[Suggestion]


class ActivityInput(RequestModel):
    date: dt.date
    exercise_id: uuid.UUID
    minutes: Annotated[int, Field(ge=1, le=600)]


class Activity(ResponseModel):
    id: uuid.UUID
    date: dt.date
    exercise: ExerciseSummary
    minutes: int
    kcal: int
    estimated: Literal[True] = True
    created_at: dt.datetime


class DayEnergyUpdate(ResponseModel):
    energy: EnergyBalance
    nutrition_completion: Annotated[float, Field(ge=0, le=1)] | None = None


class ActivityResult(DayEnergyUpdate):
    activity: Activity
