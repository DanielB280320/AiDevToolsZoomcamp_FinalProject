"""Chart response schemas (openapi.yaml tag Charts, F15)."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import Field

from app.schemas.base import ResponseModel
from app.schemas.calendar import Ratio, SessionStatus, TrainingStatus
from app.schemas.plans import ExerciseSummary

SetStatus = Literal["met", "partial", "missed", "skipped", "extra"]


class SessionChartSet(ResponseModel):
    set_no: int
    status: SetStatus
    completion: Ratio | None
    target_reps: int | None
    target_weight_kg: float | None
    target_seconds: int | None
    reps: int | None
    weight_kg: float | None
    seconds: int | None


class SessionChartExercise(ResponseModel):
    exercise: ExerciseSummary
    is_extra: bool
    completion: Ratio | None
    sets: list[SessionChartSet]


class SessionChart(ResponseModel):
    session_id: uuid.UUID
    date: dt.date
    training_day_name: str | None
    status: SessionStatus
    completion: Ratio | None
    kcal: int | None
    exercises: list[SessionChartExercise]


class ExerciseChartPoint(ResponseModel):
    date: dt.date
    session_id: uuid.UUID
    target_weight_kg: float | None
    target_reps: int | None
    target_seconds: int | None
    top_set_weight_kg: float | None
    top_set_reps: int | None
    top_set_seconds: int | None
    volume_kg: float = Field(ge=0)
    is_pr: bool


class ExerciseChart(ResponseModel):
    exercise: ExerciseSummary
    weeks: int
    points: list[ExerciseChartPoint]


class AdherenceDay(ResponseModel):
    date: dt.date
    training_status: TrainingStatus
    training_completion: Ratio | None
    nutrition_completion: Ratio | None


class AdherenceWeek(ResponseModel):
    week_start: dt.date
    sessions_planned: int
    sessions_done: int
    training_completion: Ratio | None
    nutrition_completion: Ratio | None


class AdherenceChart(ResponseModel):
    # `from` is a Python keyword.
    from_: dt.date = Field(serialization_alias="from")
    to: dt.date
    days: list[AdherenceDay]
    weeks: list[AdherenceWeek]


class DatedValue(ResponseModel):
    date: dt.date
    value: float | None


class Sparklines(ResponseModel):
    daily_balance_kcal: list[DatedValue]
    training_completion: list[DatedValue]
    weight_avg_kg: list[DatedValue]


class WeeklySummary(ResponseModel):
    week_start: dt.date
    week_end: dt.date
    estimated: Literal[True] = True
    sessions_planned: int
    sessions_done: int
    sessions_missed: int
    avg_completion: Ratio | None
    avg_daily_balance_kcal: int | None
    target_daily_balance_kcal: int | None
    weight_avg_start_kg: float | None
    weight_avg_end_kg: float | None
    weight_change_kg: float | None
    sparklines: Sparklines


class BodyChartPoint(ResponseModel):
    date: dt.date
    weight_kg: float | None
    weight_avg_7d_kg: float | None
    body_fat_pct: float | None


class BodyChart(ResponseModel):
    weeks: int
    estimated: Literal[True] = True
    points: list[BodyChartPoint]


class PeriodKpis(ResponseModel):
    sessions_planned: int
    sessions_done: int
    sessions_missed: int
    avg_training_completion: Ratio | None
    avg_nutrition_completion: Ratio | None
    active_days: int
    volume_kg: float
    personal_records: int
    avg_daily_eaten_kcal: int | None
    avg_daily_burned_exercise_kcal: int | None
    avg_daily_balance_kcal: int | None
    target_daily_balance_kcal: int | None
    weight_avg_start_kg: float | None
    weight_avg_end_kg: float | None
    weight_change_kg: float | None
    weight_change_per_week_kg: float | None


class PeriodDeltas(ResponseModel):
    sessions_planned: float | None
    sessions_done: float | None
    sessions_missed: float | None
    avg_training_completion: float | None
    avg_nutrition_completion: float | None
    active_days: float | None
    volume_kg: float | None
    personal_records: float | None
    avg_daily_eaten_kcal: float | None
    avg_daily_burned_exercise_kcal: float | None
    avg_daily_balance_kcal: float | None
    target_daily_balance_kcal: float | None
    weight_avg_start_kg: float | None
    weight_avg_end_kg: float | None
    weight_change_kg: float | None
    weight_change_per_week_kg: float | None


class PeriodSeriesPoint(ResponseModel):
    start: dt.date
    sessions_done: int
    sessions_planned: int
    volume_kg: float
    training_completion: Ratio | None
    nutrition_completion: Ratio | None
    balance_kcal: int | None
    weight_avg_kg: float | None


class PeriodSummary(ResponseModel):
    # `from` is a Python keyword.
    from_: dt.date = Field(serialization_alias="from")
    to: dt.date
    days: int
    previous_from: dt.date
    previous_to: dt.date
    bucket: Literal["day", "week"]
    estimated: Literal[True] = True
    current: PeriodKpis
    previous: PeriodKpis
    deltas: PeriodDeltas
    longest_streak_days: int
    series: list[PeriodSeriesPoint]


class ProgressTotals(ResponseModel):
    sessions_done: int
    personal_records: int
    first_session_date: dt.date | None
