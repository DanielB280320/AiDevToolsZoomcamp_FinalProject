"""Training logging endpoints (openapi.yaml, tag Logging): sets, finish, extra activities."""

import uuid
from typing import Any

from fastapi import APIRouter, Response

from app.dependencies import OwnerAccess, OwnerSession, SessionDep, TelemetryDep
from app.models import Suggestion as Row
from app.schemas.logging import (
    ActivityInput,
    ActivityResult,
    DayEnergyUpdate,
    FinishSessionRequest,
    FinishSessionResult,
    SetLogInput,
)
from app.schemas.meal_log import MealLogInput, MealLogResult
from app.schemas.problem import Problem
from app.schemas.setlog import SetLog
from app.services import calendar, meal_log, suggestions, training_log
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
    access: OwnerSession,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
    flags: FlagsDep,
) -> SetLog:
    """Log (or re-log) a set; idempotent per (session, exercise, set number) (F10.1)."""
    now = clock.now()
    user = access.athlete
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
    access: OwnerSession,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
    flags: FlagsDep,
) -> Response:
    now = clock.now()
    user = access.athlete
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
    access: OwnerSession,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
    flags: FlagsDep,
    body: FinishSessionRequest | None = None,
) -> FinishSessionResult:
    """Close the workout: completion (F10.2), kcal (F13.2) and progression suggestions (F11)."""
    now = clock.now()
    user = access.athlete
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
    access: OwnerAccess,
    body: ActivityInput,
    db: SessionDep,
    clock: ClockDep,
) -> ActivityResult:
    """Off-plan timed activity on any day; counts for burned kcal, not completion (F10.4)."""
    return training_log.log_activity(db, access.athlete, body, clock.now())


@router.delete(
    "/athletes/{athlete_id}/activities/{activity_id}",
    operation_id="deleteActivity",
    response_model=DayEnergyUpdate,
    responses={**_COMMON, 404: _PROBLEM},
)
def delete_activity(access: OwnerAccess, activity_id: uuid.UUID, db: SessionDep) -> DayEnergyUpdate:
    return training_log.delete_activity(db, access.athlete, activity_id)


@router.post(
    "/athletes/{athlete_id}/meal-logs",
    operation_id="logMeal",
    response_model=MealLogResult,
    status_code=201,
    responses={
        **_COMMON,
        200: {
            "model": MealLogResult,
            "description": "Existing log for this planned meal replaced.",
        },
        404: _PROBLEM,
        422: _PROBLEM,
    },
)
def log_meal(
    access: OwnerAccess,
    body: MealLogInput,
    response: Response,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
) -> MealLogResult:
    """Check off, adjust or skip a planned meal, or add extra food (F12). Idempotent per
    (date, planned meal): a repeat returns 200 and does not count as a new check-off (F12.3)."""
    result, new_checkoff = meal_log.log_meal(db, access.athlete, body, clock.now())
    if new_checkoff:
        telemetry.metrics.meal_checked_off()
    if result.meal_log.planned_meal_id is not None and not new_checkoff:
        response.status_code = 200
    return result


@router.delete(
    "/athletes/{athlete_id}/meal-logs/{meal_log_id}",
    operation_id="deleteMealLog",
    response_model=DayEnergyUpdate,
    responses={**_COMMON, 404: _PROBLEM},
)
def delete_meal_log(access: OwnerAccess, meal_log_id: uuid.UUID, db: SessionDep) -> DayEnergyUpdate:
    return meal_log.delete_meal_log(db, access.athlete, meal_log_id)
