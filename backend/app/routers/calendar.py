"""Calendar endpoints (openapi.yaml, tag Calendar)."""

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query

from app.dependencies import CurrentUser, SessionDep
from app.schemas.base import NoNul
from app.schemas.calendar import CalendarRange, DayView, MoveSessionRequest, Session
from app.schemas.problem import Problem
from app.services import calendar
from app.services.clock import ClockDep

router = APIRouter(tags=["Calendar"])

_PROBLEM: dict[str, Any] = {"model": Problem}
_COMMON: dict[int | str, dict[str, Any]] = {400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM}


@router.get(
    "/athletes/{athlete_id}/days/{date}",
    operation_id="getDay",
    response_model=DayView,
    responses={**_COMMON, 404: _PROBLEM},
)
def get_day(
    athlete_id: str,
    date: Annotated[str, Path(pattern=r"^(today|\d{4}-\d{2}-\d{2})$"), NoNul],
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
) -> DayView:
    """One day for the Today view; materialises the day's session when planned (idempotent)."""
    calendar.athlete_scope(user, athlete_id)
    return calendar.get_day(db, user, date, clock.now())


@router.get(
    "/athletes/{athlete_id}/calendar",
    operation_id="getCalendar",
    response_model=CalendarRange,
    responses=_COMMON,
)
def get_calendar(
    athlete_id: str,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
    from_: Annotated[dt.date, Query(alias="from")],
    to: Annotated[dt.date, Query()],
) -> CalendarRange:
    """Day summaries from `from` to `to` inclusive (max 42 days)."""
    calendar.athlete_scope(user, athlete_id)
    return calendar.get_calendar(db, user, from_, to, clock.now())


@router.get(
    "/sessions/{session_id}",
    operation_id="getSession",
    response_model=Session,
    responses={**_COMMON, 404: _PROBLEM},
)
def get_session(
    session_id: uuid.UUID, user: CurrentUser, db: SessionDep, clock: ClockDep
) -> Session:
    return calendar.get_session(db, user, session_id, clock.now())


@router.post(
    "/sessions/{session_id}/move",
    operation_id="moveSession",
    response_model=Session,
    responses={**_COMMON, 404: _PROBLEM, 409: _PROBLEM, 422: _PROBLEM},
)
def move_session(
    session_id: uuid.UUID,
    body: MoveSessionRequest,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
) -> Session:
    """Move a not-finished session within its ISO week (D45)."""
    return calendar.move_session(db, user, session_id, body.date, clock.now())
