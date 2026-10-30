"""Plan response schemas (openapi.yaml `Plan`, `TrainingDay`, `PlannedExercise`)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.exercises import ExerciseEquipment, ExerciseType, MuscleGroup
from app.schemas.foods import FoodGrams, Macros, MealItem, MealSlot
from app.schemas.users import UserRef

PlanSource = Literal["generated", "custom"]
ProgressionRule = Literal["linear", "double", "manual"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ExerciseSummary(ResponseModel):
    id: uuid.UUID
    name: str
    type: ExerciseType
    equipment: ExerciseEquipment
    muscle_group: MuscleGroup


class PlannedExercise(ResponseModel):
    id: uuid.UUID
    exercise: ExerciseSummary
    order: int
    sets: int
    reps_min: int | None
    reps_max: int | None
    target_weight_kg: float | None
    target_seconds: int | None
    rest_seconds: int
    rule: ProgressionRule
    increment_kg: float
    deload_enabled: bool
    calibration_hint: str | None


class TrainingDay(ResponseModel):
    id: uuid.UUID
    weekday: Weekday
    name: str
    order: int
    exercises: list[PlannedExercise]
    estimated_minutes: int
    planned_kcal: int
    edited_by: UserRef | None


class MealSummary(ResponseModel):
    id: uuid.UUID
    name: str
    slots: list[MealSlot]


class PlannedMeal(ResponseModel):
    id: uuid.UUID
    slot: MealSlot
    order: int
    meal: MealSummary
    portion_factor: float
    items: list[MealItem]
    totals: Macros


class MealDay(ResponseModel):
    id: uuid.UUID
    weekday: Weekday
    meals: list[PlannedMeal]
    totals: Macros
    warning: str | None
    edited_by: UserRef | None


class Plan(ResponseModel):
    id: uuid.UUID
    athlete_id: uuid.UUID
    version: int
    source: PlanSource
    active: bool
    revision: int
    created_by: UserRef | None
    created_at: dt.datetime
    updated_at: dt.datetime
    training_days: list[TrainingDay]
    meal_days: list[MealDay]
    warnings: list[str]


class PlanVersionSummary(ResponseModel):
    id: uuid.UUID
    version: int
    source: PlanSource
    active: bool
    created_by: UserRef | None
    created_at: dt.datetime


class PlanVersionList(ResponseModel):
    items: list[PlanVersionSummary]


# ───────────── requests (custom mode, F8) ─────────────


class PlannedExerciseInput(RequestModel):
    id: uuid.UUID | None = None
    exercise_id: uuid.UUID
    sets: Annotated[int, Field(ge=1, le=10)]
    reps_min: Annotated[int, Field(ge=1, le=100)] | None = None
    reps_max: Annotated[int, Field(ge=1, le=100)] | None = None
    target_weight_kg: Annotated[float, Field(ge=0, le=500, allow_inf_nan=False)] | None = None
    target_seconds: Annotated[int, Field(ge=5, le=14400)] | None = None
    rest_seconds: Annotated[int, Field(ge=0, le=600)] = 90
    rule: ProgressionRule
    increment_kg: Annotated[float, Field(ge=0, le=20, allow_inf_nan=False)] | None = None
    deload_enabled: bool = True


class TrainingDayInput(RequestModel):
    id: uuid.UUID | None = None
    weekday: Weekday
    name: Annotated[str, Field(min_length=1, max_length=60)]
    exercises: Annotated[list[PlannedExerciseInput], Field(max_length=20)]


class TrainingPlanUpdate(RequestModel):
    revision: Annotated[int, Field(ge=0)]
    training_days: Annotated[list[TrainingDayInput], Field(max_length=7)]


class PlannedMealInput(RequestModel):
    id: uuid.UUID | None = None
    slot: MealSlot
    meal_id: uuid.UUID
    portion_factor: Annotated[float, Field(ge=0.25, le=3, allow_inf_nan=False)] = 1
    items: Annotated[list[FoodGrams], Field(min_length=1, max_length=30)] | None = None


class MealDayInput(RequestModel):
    weekday: Weekday
    meals: Annotated[list[PlannedMealInput], Field(max_length=10)]


class MealPlanUpdate(RequestModel):
    revision: Annotated[int, Field(ge=0)]
    meal_days: Annotated[list[MealDayInput], Field(max_length=7)]


class RegeneratePlanRequest(RequestModel):
    scope: Literal["all", "training", "meals"] = "all"
