"""Calendar response/request schemas (openapi.yaml `DayView`, `CalendarDay`, `Session`, ...).

Fields owned by later issues (meals #37, energy #38, suggestions #85, notes #49, set logs #29)
are present as the contract requires but empty / zero / null until those land.
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.plans import ExerciseSummary, ProgressionRule, Weekday

SessionStatus = Literal["planned", "in_progress", "done", "missed"]
TrainingStatus = Literal["rest", "planned", "in_progress", "done", "missed"]
Ratio = Annotated[float, Field(ge=0, le=1)]


class Macros(ResponseModel):
    kcal: int = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0


class Burned(ResponseModel):
    total_kcal: int = 0
    baseline_kcal: int = 0
    training_kcal: int = 0
    activities_kcal: int = 0


class EnergyBalance(ResponseModel):
    date: dt.date
    estimated: Literal[True] = True
    eaten: Macros = Macros()
    planned: Macros = Macros()
    target: Macros = Macros()
    burned: Burned = Burned()
    balance_kcal: int = 0
    target_balance_kcal: int = 0


class SessionSet(ResponseModel):
    set_no: int
    is_extra: bool
    target_reps: int | None
    target_weight_kg: float | None
    target_seconds: int | None
    log: None = None  # set logs arrive with #29


class SessionExercise(ResponseModel):
    planned_exercise_id: uuid.UUID | None
    exercise: ExerciseSummary
    order: int
    is_extra: bool
    rule: ProgressionRule | None
    sets: list[SessionSet]
    reps_min: int | None
    reps_max: int | None
    rest_seconds: int
    calibration_hint: str | None
    completion: Ratio | None
    pending_suggestion_id: uuid.UUID | None


class Session(ResponseModel):
    id: uuid.UUID
    athlete_id: uuid.UUID
    plan_id: uuid.UUID
    plan_version: int
    training_day_id: uuid.UUID
    training_day_name: str
    date: dt.date
    original_date: dt.date | None
    status: SessionStatus
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    editable_until: dt.datetime
    completion: Ratio | None
    kcal: int | None
    estimated: Literal[True] = True
    exercises: list[SessionExercise]


class DayView(ResponseModel):
    date: dt.date
    weekday: Weekday
    is_today: bool
    training_status: TrainingStatus
    session: Session | None
    meals: list[Any]
    extra_meal_logs: list[Any]
    activities: list[Any]
    energy: EnergyBalance
    training_completion: Ratio | None
    nutrition_completion: Ratio | None
    pending_suggestions: list[Any]
    weigh_in_hint: None = None
    notes: list[Any]
    meal_warning: str | None = None


class CalendarDay(ResponseModel):
    date: dt.date
    weekday: Weekday
    is_today: bool
    training_status: TrainingStatus
    session_id: uuid.UUID | None
    training_day_name: str | None
    moved: bool
    training_completion: Ratio | None
    nutrition_completion: Ratio | None = None
    planned_meal_count: int = 0
    eaten_meal_count: int = 0
    energy: EnergyBalance


class CalendarRange(ResponseModel):
    # `from` is a Python keyword.
    from_: dt.date = Field(serialization_alias="from")
    to: dt.date
    timezone: str
    days: list[CalendarDay]


class MoveSessionRequest(RequestModel):
    date: dt.date
