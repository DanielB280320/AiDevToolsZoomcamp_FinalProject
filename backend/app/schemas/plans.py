"""Plan response schemas (openapi.yaml `Plan`, `TrainingDay`, `PlannedExercise`)."""

import datetime as dt
import uuid
from typing import Literal

from app.schemas.base import ResponseModel
from app.schemas.exercises import ExerciseEquipment, ExerciseType, MuscleGroup
from app.schemas.foods import Macros, MealItem, MealSlot
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
    created_by: UserRef
    created_at: dt.datetime
    updated_at: dt.datetime
    training_days: list[TrainingDay]
    meal_days: list[MealDay]
    warnings: list[str]
