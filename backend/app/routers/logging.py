"""Training logging endpoints (openapi.yaml, tag Logging): sets, finish, extra activities."""

import uuid
from typing import Any

from fastapi import APIRouter, Response

from app.dependencies import CurrentUser, SessionDep, TelemetryDep
from app.models import Suggestion as Row
from app.schemas.logging import (
    ActivityInput,
    ActivityResult,
    DayEnergyUpdate,
    FinishSessionRequest,
    FinishSessionResult,
    SetLogInput,
)
from app.schemas.problem import Problem
from app.schemas.setlog import SetLog
from app.services import calendar, suggestions, training_log
from app.services.clock import ClockDep, local_today
from app.services.flags import FlagsDep
from app.telemetry import Telemetry

router = APIRouter(tags=["Logging"])

_PROBLEM: dict[str, Any] = {"model": Problem}
_COMMON: dict[int | str, dict[str, Any]] = {400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM}


def _count(telemetry: Telemetry, created: list[Row]) -> None:
    for row in created:
        telemetry.metrics.suggestion_generated(row.kind, row.rule)  # type: ignore[arg-type]


@router.post(
    "/sessions/{session_id}/sets",
    operation_id="logSet",
    response_model=SetLog,
    status_code=201,
    responses={
        **_COMMON,
        200: {"model": SetLog, "description": "Existing set log replaced."},
        404: _PROBLEM,
        409: _PROBLEM,
        422: _PROBLEM,
    },
)
def log_set(
    session_id: uuid.UUID,
    body: SetLogInput,
    response: Response,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
    flags: FlagsDep,
) -> SetLog:
    """Log (or re-log) a set; idempotent per (session, exercise, set number) (F10.1)."""
    now = clock.now()
    log, created = training_log.log_set(db, user, session_id, body, now)
    telemetry.metrics.set_logged()
    # Editing a finished session replaces its pending suggestions (F10.3).
    _count(
        telemetry,
        suggestions.refresh_for_session(db, user, session_id, flags.progression_engine, now),
    )
    if not created:
        response.status_code = 200
    return SetLog.model_validate(log, from_attributes=True)


@router.delete(
    "/sessions/{session_id}/sets/{set_log_id}",
    operation_id="deleteSetLog",
    status_code=204,
    responses={**_COMMON, 404: _PROBLEM, 409: _PROBLEM},
)
def delete_set_log(
    session_id: uuid.UUID,
    set_log_id: uuid.UUID,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
    flags: FlagsDep,
) -> Response:
    now = clock.now()
    training_log.delete_set(db, user, session_id, set_log_id, now)
    _count(
        telemetry,
        suggestions.refresh_for_session(db, user, session_id, flags.progression_engine, now),
    )
    return Response(status_code=204)


@router.post(
    "/sessions/{session_id}/finish",
    operation_id="finishSession",
    response_model=FinishSessionResult,
    responses={**_COMMON, 404: _PROBLEM, 409: _PROBLEM, 422: _PROBLEM},
)
def finish_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
    flags: FlagsDep,
    body: FinishSessionRequest | None = None,
) -> FinishSessionResult:
    """Close the workout: completion (F10.2), kcal (F13.2) and progression suggestions (F11)."""
    now = clock.now()
    row, first = training_log.finish_session(
        db, user, session_id, body.finished_at if body else None, now
    )
    if first:
        telemetry.metrics.workout_finished()
    created = suggestions.refresh_for_session(db, user, session_id, flags.progression_engine, now)
    _count(telemetry, created)
    view = calendar.session_view(db, user, row, local_today(now, user.timezone))
    return FinishSessionResult(session=view, suggestions=[suggestions.view(db, r) for r in created])


@router.post(
    "/athletes/{athlete_id}/activities",
    operation_id="logActivity",
    response_model=ActivityResult,
    status_code=201,
    responses={**_COMMON, 404: _PROBLEM, 422: _PROBLEM},
)
def log_activity(
    athlete_id: str,
    body: ActivityInput,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
) -> ActivityResult:
    """Off-plan timed activity on any day; counts for burned kcal, not completion (F10.4)."""
    calendar.athlete_scope(user, athlete_id)
    return training_log.log_activity(db, user, body, clock.now())


@router.delete(
    "/athletes/{athlete_id}/activities/{activity_id}",
    operation_id="deleteActivity",
    response_model=DayEnergyUpdate,
    responses={**_COMMON, 404: _PROBLEM},
)
def delete_activity(
    athlete_id: str, activity_id: uuid.UUID, user: CurrentUser, db: SessionDep
) -> DayEnergyUpdate:
    calendar.athlete_scope(user, athlete_id)
    return training_log.delete_activity(db, user, activity_id)
