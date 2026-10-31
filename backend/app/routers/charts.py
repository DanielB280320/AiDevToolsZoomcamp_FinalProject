"""Chart endpoints (openapi.yaml, tag Charts): pre-aggregated series for the progress views (F15).

Owner or linked coach (`OwnerOrCoachAccess`); every other id is `403 not_linked` (D41).
"""

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.dependencies import OwnerOrCoachAccess, SessionDep
from app.schemas.charts import (
    AdherenceChart,
    BodyChart,
    ExerciseChart,
    SessionChart,
    WeeklySummary,
)
from app.schemas.problem import Problem
from app.services import charts
from app.services.clock import ClockDep

router = APIRouter(tags=["Charts"])

_PROBLEM: dict[str, Any] = {"model": Problem}
_COMMON: dict[int | str, dict[str, Any]] = {400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM}
Weeks = Annotated[int, Query(description="4, 12, 26 or 52 (default 12).")]


@router.get(
    "/athletes/{athlete_id}/charts/session/{session_id}",
    operation_id="getSessionChart",
    response_model=SessionChart,
    responses={**_COMMON, 404: _PROBLEM},
)
def get_session_chart(
    access: OwnerOrCoachAccess, session_id: uuid.UUID, db: SessionDep, clock: ClockDep
) -> SessionChart:
    return charts.session_chart(db, access.athlete, session_id, clock.now())


@router.get(
    "/athletes/{athlete_id}/charts/exercise/{exercise_id}",
    operation_id="getExerciseChart",
    response_model=ExerciseChart,
    responses={**_COMMON, 404: _PROBLEM},
)
def get_exercise_chart(
    access: OwnerOrCoachAccess,
    exercise_id: uuid.UUID,
    db: SessionDep,
    clock: ClockDep,
    weeks: Weeks = 12,
) -> ExerciseChart:
    return charts.exercise_chart(
        db, access.athlete, exercise_id, charts.check_weeks(weeks), clock.now()
    )


@router.get(
    "/athletes/{athlete_id}/charts/adherence",
    operation_id="getAdherenceChart",
    response_model=AdherenceChart,
    responses=_COMMON,
)
def get_adherence_chart(
    access: OwnerOrCoachAccess,
    db: SessionDep,
    clock: ClockDep,
    from_: Annotated[dt.date, Query(alias="from")],
    to: Annotated[dt.date, Query()],
) -> AdherenceChart:
    return charts.adherence_chart(db, access.athlete, from_, to, clock.now())


@router.get(
    "/athletes/{athlete_id}/charts/weekly-summary",
    operation_id="getWeeklySummary",
    response_model=WeeklySummary,
    responses=_COMMON,
)
def get_weekly_summary(
    access: OwnerOrCoachAccess,
    db: SessionDep,
    clock: ClockDep,
    week_start: Annotated[dt.date | None, Query()] = None,
) -> WeeklySummary:
    return charts.weekly_summary(db, access.athlete, week_start, clock.now())


@router.get(
    "/athletes/{athlete_id}/charts/body",
    operation_id="getBodyChart",
    response_model=BodyChart,
    responses=_COMMON,
)
def get_body_chart(
    access: OwnerOrCoachAccess, db: SessionDep, clock: ClockDep, weeks: Weeks = 12
) -> BodyChart:
    return charts.body_chart(db, access.athlete, charts.check_weeks(weeks), clock.now())
