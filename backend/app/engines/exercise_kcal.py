"""F13.2 Exercise kcal engine: MET formula, minute estimation, planned and logged totals.

`kcal = MET × 3.5 × body_weight_kg ÷ 200 × minutes` (spec F13.2).

- Strength / bodyweight: minutes = sets × (rest_seconds + 45 s) ÷ 60.
- Timed / cardio: minutes = the duration (planned: sets × target_seconds; logged: Σ durations).
- Planned weekly kcal (sum over a weekly template) ÷ 7 is the daily exercise allowance in the
  F3.4 calorie target.
- Logged session kcal sums every performed exercise (extra sets and exercises included) plus
  extra activities, which use the same formula with their minutes.

Pure (ADR 0004): plain inputs in, results with an `explanation` out. The caller picks the body
weight ("most recent weight on or before the date"); this module never reads a clock or a
database. Intermediate values are never rounded; only the `kcal` output is rounded to a whole
`Kcal` (half up), once per result.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.engines.constants import (
    DEFAULT_REST_SECONDS,
    MET_KCAL_DIVISOR,
    MET_O2_ML_PER_KG_MIN,
    PLANNED_EXERCISE_KCAL_DAYS,
    WORKING_SECONDS_PER_SET,
)

type Kcal = int
"""Whole estimated kilocalories (openapi `Kcal`: integer)."""

ExerciseType = Literal["strength", "bodyweight", "timed"]
SET_BASED_TYPES: frozenset[str] = frozenset({"strength", "bodyweight"})
EXERCISE_TYPES: frozenset[str] = frozenset({"strength", "bodyweight", "timed"})

FORMULA = "MET × 3.5 × body weight kg ÷ 200 × minutes"


# --- inputs ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedExercise:
    """One exercise of a planned training day.

    `rest_seconds` is used for strength/bodyweight, `target_seconds` (per set) for timed.
    """

    exercise_type: ExerciseType
    met: float
    sets: int
    rest_seconds: int = 0
    target_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class PlannedDay:
    """A training day of the weekly template (e.g. weekday `mon`) and its planned exercises."""

    label: str
    exercises: Sequence[PlannedExercise]


@dataclass(frozen=True, slots=True)
class LoggedExercise:
    """One exercise performed in a session, planned or extra.

    Strength/bodyweight: `performed_sets` counts every logged (not skipped) set, extra sets
    included, and `rest_seconds` is the planned rest (default 90 s for extra exercises).
    Timed: `durations_seconds` holds the logged duration of each performed set.
    """

    exercise_type: ExerciseType
    met: float
    performed_sets: int = 0
    rest_seconds: int = DEFAULT_REST_SECONDS
    durations_seconds: Sequence[float] = ()


@dataclass(frozen=True, slots=True)
class ExtraActivity:
    """An off-plan activity (e.g. football 60 min) from the timed/cardio catalog."""

    met: float
    minutes: float


# --- outputs --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExerciseKcal:
    """Result of the MET formula for one exercise or activity."""

    kcal: Kcal
    kcal_exact: float
    met: float
    body_weight_kg: float
    minutes: float
    explanation: str


@dataclass(frozen=True, slots=True)
class DayKcal:
    """Planned kcal of one training day (unrounded parts, one rounded total)."""

    label: str
    kcal: Kcal
    kcal_exact: float
    parts: tuple[ExerciseKcal, ...]


@dataclass(frozen=True, slots=True)
class PlannedWeeklyKcal:
    """Planned weekly exercise kcal and its daily average for F3.4."""

    weekly_kcal: Kcal
    weekly_kcal_exact: float
    daily_kcal: Kcal
    daily_kcal_exact: float
    days: tuple[DayKcal, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class LoggedKcal:
    """Exercise kcal of a finished session and/or a day's extra activities."""

    kcal: Kcal
    kcal_exact: float
    exercises: tuple[ExerciseKcal, ...]
    activities: tuple[ExerciseKcal, ...]
    explanation: str


# --- helpers --------------------------------------------------------------------------------


def round_kcal(value: float) -> Kcal:
    """Round a non-negative kcal value to a whole `Kcal`, half up (not banker's rounding)."""
    return math.floor(value + 0.5)


def _fmt(value: float) -> str:
    """Short, stable number formatting for explanations: 80 → '80', 6.75 → '6.75'."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _part_summary(part: ExerciseKcal) -> str:
    return f"MET {_fmt(part.met)} × {_fmt(part.minutes)} min = {_fmt(part.kcal_exact)}"


def _require_finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _require_positive(name: str, value: float) -> None:
    _require_finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")


def _require_non_negative(name: str, value: float) -> None:
    _require_finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _require_type(exercise_type: str) -> None:
    if exercise_type not in EXERCISE_TYPES:
        raise ValueError(f"unknown exercise type {exercise_type!r}")


# --- minute estimation ----------------------------------------------------------------------


def set_based_minutes(sets: int, rest_seconds: float) -> float:
    """Strength/bodyweight minutes: sets × (rest_seconds + 45 s) ÷ 60. Zero sets → 0 minutes."""
    _require_non_negative("sets", sets)
    _require_non_negative("rest_seconds", rest_seconds)
    if sets == 0:
        return 0.0
    return sets * (rest_seconds + WORKING_SECONDS_PER_SET) / 60


def duration_minutes(seconds: float) -> float:
    """Timed/cardio minutes: the duration in seconds ÷ 60."""
    _require_non_negative("duration seconds", seconds)
    return seconds / 60


# --- MET formula ----------------------------------------------------------------------------


def _exact_kcal(met: float, body_weight_kg: float, minutes: float) -> float:
    _require_positive("met", met)
    _require_positive("body_weight_kg", body_weight_kg)
    _require_non_negative("minutes", minutes)
    return met * MET_O2_ML_PER_KG_MIN * body_weight_kg / MET_KCAL_DIVISOR * minutes


def exercise_kcal(
    met: float, body_weight_kg: float, minutes: float, *, minutes_rule: str = ""
) -> ExerciseKcal:
    """kcal = MET × 3.5 × body_weight_kg ÷ 200 × minutes.

    Raises `ValueError` for MET ≤ 0, body weight ≤ 0, negative minutes or non-finite input.
    `minutes_rule` (optional) is appended to the explanation to show how minutes were derived.
    """
    exact = _exact_kcal(met, body_weight_kg, minutes)
    kcal = round_kcal(exact)
    explanation = (
        f"Exercise kcal = {FORMULA} = {_fmt(met)} × {_fmt(MET_O2_ML_PER_KG_MIN)} × "
        f"{_fmt(body_weight_kg)} kg ÷ {_fmt(MET_KCAL_DIVISOR)} × {_fmt(minutes)} min "
        f"= {kcal} kcal (estimated)"
    )
    if minutes_rule:
        explanation += f"; minutes: {minutes_rule}"
    return ExerciseKcal(
        kcal=kcal,
        kcal_exact=exact,
        met=met,
        body_weight_kg=body_weight_kg,
        minutes=minutes,
        explanation=explanation,
    )


# --- planned version (F3.4 input) -----------------------------------------------------------


def _planned_part(exercise: PlannedExercise, body_weight_kg: float) -> ExerciseKcal:
    _require_type(exercise.exercise_type)
    if exercise.exercise_type in SET_BASED_TYPES:
        minutes = set_based_minutes(exercise.sets, exercise.rest_seconds)
        rule = (
            f"{exercise.sets} sets × ({_fmt(exercise.rest_seconds)} s rest + "
            f"{WORKING_SECONDS_PER_SET} s work) ÷ 60 = {_fmt(minutes)} min"
        )
    else:
        if exercise.target_seconds is None:
            raise ValueError("timed exercise needs target_seconds")
        _require_non_negative("sets", exercise.sets)
        seconds = exercise.sets * exercise.target_seconds
        minutes = duration_minutes(seconds)
        rule = (
            f"{exercise.sets} sets × {_fmt(exercise.target_seconds)} s ÷ 60 = {_fmt(minutes)} min"
        )
    return exercise_kcal(exercise.met, body_weight_kg, minutes, minutes_rule=rule)


def planned_weekly_kcal(days: Sequence[PlannedDay], body_weight_kg: float) -> PlannedWeeklyKcal:
    """Planned weekly exercise kcal over a weekly template, and its daily average (÷ 7) for F3.4.

    Rest days are simply absent from `days`. The daily value is weekly ÷ 7 over all 7 days.
    """
    _require_positive("body_weight_kg", body_weight_kg)
    day_results: list[DayKcal] = []
    for day in days:
        parts = tuple(_planned_part(ex, body_weight_kg) for ex in day.exercises)
        exact = math.fsum(p.kcal_exact for p in parts)
        day_results.append(
            DayKcal(label=day.label, kcal=round_kcal(exact), kcal_exact=exact, parts=parts)
        )
    weekly_exact = math.fsum(d.kcal_exact for d in day_results)
    daily_exact = weekly_exact / PLANNED_EXERCISE_KCAL_DAYS
    weekly = round_kcal(weekly_exact)
    daily = round_kcal(daily_exact)
    per_day = (
        "; ".join(
            f"{d.label}: "
            + " + ".join(_part_summary(p) for p in d.parts)
            + f" = {_fmt(d.kcal_exact)}"
            if d.parts
            else f"{d.label}: 0"
            for d in day_results
        )
        or "no training days"
    )
    explanation = (
        f"Planned exercise kcal per training day ({FORMULA}, body weight "
        f"{_fmt(body_weight_kg)} kg; strength/bodyweight minutes = sets × (rest + "
        f"{WORKING_SECONDS_PER_SET} s) ÷ 60, timed minutes = sets × target seconds ÷ 60): "
        f"{per_day}. Weekly total = {weekly} kcal; daily average = "
        f"{_fmt(weekly_exact)} ÷ {PLANNED_EXERCISE_KCAL_DAYS} = {daily} kcal/day (estimated)"
    )
    return PlannedWeeklyKcal(
        weekly_kcal=weekly,
        weekly_kcal_exact=weekly_exact,
        daily_kcal=daily,
        daily_kcal_exact=daily_exact,
        days=tuple(day_results),
        explanation=explanation,
    )


# --- logged version (session finish, extra activities) --------------------------------------


def _logged_part(exercise: LoggedExercise, body_weight_kg: float) -> ExerciseKcal:
    _require_type(exercise.exercise_type)
    if exercise.exercise_type in SET_BASED_TYPES:
        minutes = set_based_minutes(exercise.performed_sets, exercise.rest_seconds)
        rule = (
            f"{exercise.performed_sets} performed sets × ({_fmt(exercise.rest_seconds)} s rest + "
            f"{WORKING_SECONDS_PER_SET} s work) ÷ 60 = {_fmt(minutes)} min"
        )
    else:
        for seconds in exercise.durations_seconds:
            _require_non_negative("duration seconds", seconds)
        total = math.fsum(exercise.durations_seconds)
        minutes = duration_minutes(total)
        rule = f"logged duration {_fmt(total)} s ÷ 60 = {_fmt(minutes)} min"
    return exercise_kcal(exercise.met, body_weight_kg, minutes, minutes_rule=rule)


def logged_kcal(
    exercises: Sequence[LoggedExercise],
    body_weight_kg: float,
    activities: Sequence[ExtraActivity] = (),
) -> LoggedKcal:
    """Exercise kcal from logged sets/durations and extra activities, rounded once at the end.

    Pass a session's exercises (planned and extra) to get the session kcal stored on finish;
    pass a day's extra activities (alone or together) for the F13.1 burned total.
    """
    _require_positive("body_weight_kg", body_weight_kg)
    ex_parts = tuple(_logged_part(ex, body_weight_kg) for ex in exercises)
    act_parts = tuple(
        exercise_kcal(a.met, body_weight_kg, a.minutes, minutes_rule="activity minutes")
        for a in activities
    )
    exact = math.fsum(p.kcal_exact for p in (*ex_parts, *act_parts))
    kcal = round_kcal(exact)
    exercises_text = ", ".join(_part_summary(p) for p in ex_parts) or "none"
    activities_text = ", ".join(_part_summary(p) for p in act_parts) or "none"
    explanation = (
        f"Logged exercise kcal = Σ ({FORMULA}) at body weight {_fmt(body_weight_kg)} kg "
        f"(strength/bodyweight minutes = performed sets × (rest + {WORKING_SECONDS_PER_SET} s)"
        f" ÷ 60, timed minutes = logged duration). Exercises: {exercises_text}. "
        f"Extra activities: {activities_text}. Total {_fmt(exact)} → {kcal} kcal (estimated)"
    )
    return LoggedKcal(
        kcal=kcal,
        kcal_exact=exact,
        exercises=ex_parts,
        activities=act_parts,
        explanation=explanation,
    )
