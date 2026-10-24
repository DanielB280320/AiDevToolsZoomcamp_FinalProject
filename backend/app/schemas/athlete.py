"""Onboarding, profile, body-metric and targets schemas (openapi.yaml, tag Profile)."""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.plans import Plan

Sex = Literal["male", "female", "unspecified"]
Lifestyle = Literal["sedentary", "lightly_active", "active", "very_active"]
Goal = Literal["recomposition", "muscle_gain", "cutting", "maintenance", "wellness"]
Experience = Literal["beginner", "intermediate", "advanced"]
TrainingEquipment = Literal["full_gym", "home_dumbbells", "bodyweight_only"]
Diet = Literal["omnivore", "vegetarian", "vegan", "pescatarian"]
Allergen = Literal["gluten", "lactose", "nuts", "eggs", "soy", "shellfish", "fish"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
BodyFatMethod = Literal["entered", "navy"]

MeasurementCm = Annotated[float, Field(ge=20, le=200, allow_inf_nan=False)]


def _unique(value: list[Any]) -> list[Any]:
    if len(set(value)) != len(value):
        raise PydanticCustomError("invalid_choice", "Remove the duplicate entries.")
    return value


class AthleteProfileInput(RequestModel):
    sex: Sex
    height_cm: Annotated[float, Field(ge=120, le=230, allow_inf_nan=False)]
    lifestyle: Lifestyle
    goal: Goal
    experience: Experience
    days_per_week: Annotated[int, Field(ge=2, le=6)]
    preferred_days: Annotated[list[Weekday], Field(min_length=2, max_length=6)]
    session_minutes: Literal[30, 45, 60, 75, 90]
    equipment: TrainingEquipment
    avoided_exercise_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    diet: Diet
    allergies: list[Allergen] = Field(default_factory=list)
    meals_per_day: Literal[3, 4, 5]

    @field_validator("preferred_days", mode="after")
    @classmethod
    def _preferred_days_match(cls, value: list[str], info: ValidationInfo) -> list[str]:
        _unique(value)
        days = info.data.get("days_per_week")
        if days is not None and len(value) != days:
            raise PydanticCustomError(
                "invalid_choice", "Pick exactly as many preferred days as training days per week."
            )
        return value

    @field_validator("avoided_exercise_ids", "allergies", mode="after")
    @classmethod
    def _no_duplicates(cls, value: list[Any]) -> list[Any]:
        return _unique(value)


class OnboardingBodyMetric(RequestModel):
    """`entered` needs `body_fat_pct`; `navy` needs neck and waist (+ hip for female /
    unspecified, checked against the profile's sex); `skip` uses none of them."""

    weight_kg: Annotated[float, Field(ge=35, le=300, allow_inf_nan=False)]
    body_fat_method: Literal["entered", "navy", "skip"]
    body_fat_pct: Annotated[float, Field(ge=3, le=60, allow_inf_nan=False)] | None = None
    neck_cm: MeasurementCm | None = None
    waist_cm: MeasurementCm | None = None
    hip_cm: MeasurementCm | None = None


class OnboardingRequest(RequestModel):
    profile: AthleteProfileInput
    body_metric: OnboardingBodyMetric


class AthleteProfile(ResponseModel):
    athlete_id: uuid.UUID
    sex: Sex
    height_cm: float
    lifestyle: Lifestyle
    goal: Goal
    experience: Experience
    days_per_week: int
    preferred_days: list[Weekday]
    session_minutes: int
    equipment: TrainingEquipment
    avoided_exercise_ids: list[uuid.UUID]
    diet: Diet
    allergies: list[Allergen]
    meals_per_day: int
    updated_at: dt.datetime


class BodyMetric(ResponseModel):
    id: uuid.UUID
    date: dt.date
    weight_kg: float | None
    body_fat_pct: float | None
    body_fat_method: BodyFatMethod | None
    body_fat_explanation: str | None
    neck_cm: float | None
    waist_cm: float | None
    hip_cm: float | None
    created_at: dt.datetime


class Targets(ResponseModel):
    id: uuid.UUID
    athlete_id: uuid.UUID
    valid_from: dt.date
    estimated: Literal[True] = True
    bmr_formula: Literal["katch_mcardle", "mifflin_st_jeor"]
    bmr_kcal: int
    lifestyle_factor: float
    baseline_kcal: int
    planned_exercise_kcal_per_day: int
    goal_adjustment_pct: float
    kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float
    target_balance_kcal: int
    floor_applied: bool
    floor_kcal: int
    carbs_clamped: bool
    weight_used_kg: float
    body_fat_pct_used: float | None
    explanation: str
    inputs: dict[str, Any]
    created_at: dt.datetime


class OnboardingResult(ResponseModel):
    profile: AthleteProfile
    body_metric: BodyMetric
    targets: Targets
    plan: Plan


class ProfileUpdateResult(ResponseModel):
    profile: AthleteProfile
    targets: Targets
    targets_changed: bool
