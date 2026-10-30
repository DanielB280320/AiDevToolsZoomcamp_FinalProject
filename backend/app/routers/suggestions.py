"""Suggestion endpoints (openapi.yaml, tag Suggestions): list, accept, reject (F11)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, SessionDep, TelemetryDep
from app.schemas.problem import Problem
from app.schemas.suggestions import (
    AcceptSuggestionRequest,
    Suggestion,
    SuggestionKind,
    SuggestionList,
    SuggestionStatus,
)
from app.services import calendar, suggestions
from app.services.clock import ClockDep

router = APIRouter(tags=["Suggestions"])

_PROBLEM: dict[str, Any] = {"model": Problem}
_COMMON: dict[int | str, dict[str, Any]] = {400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM}


@router.get(
    "/athletes/{athlete_id}/suggestions",
    operation_id="listSuggestions",
    response_model=SuggestionList,
    responses=_COMMON,
)
def list_suggestions(
    athlete_id: str,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
    status: Annotated[SuggestionStatus, Query()] = "pending",
    kind: Annotated[SuggestionKind | None, Query()] = None,
) -> SuggestionList:
    """Newest first; `status` defaults to `pending`."""
    owner = calendar.athlete_scope(user, athlete_id)
    return suggestions.list_suggestions(db, owner, status, kind, clock.now())


@router.post(
    "/suggestions/{suggestion_id}/accept",
    operation_id="acceptSuggestion",
    response_model=Suggestion,
    responses={**_COMMON, 409: _PROBLEM, 422: _PROBLEM},
)
def accept_suggestion(
    suggestion_id: uuid.UUID,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
    body: AcceptSuggestionRequest | None = None,
) -> Suggestion:
    """Accept, optionally with edited values; they become the exercise's next targets."""
    row = suggestions.accept(db, user, suggestion_id, body.overrides if body else None, clock.now())
    telemetry.metrics.suggestion_decided(row.kind, "accepted")  # type: ignore[arg-type]
    return suggestions.view(db, row)


@router.post(
    "/suggestions/{suggestion_id}/reject",
    operation_id="rejectSuggestion",
    response_model=Suggestion,
    responses={**_COMMON, 409: _PROBLEM},
)
def reject_suggestion(
    suggestion_id: uuid.UUID,
    user: CurrentUser,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
) -> Suggestion:
    """Reject; nothing else changes (F11.3)."""
    row = suggestions.reject(db, user, suggestion_id, clock.now())
    telemetry.metrics.suggestion_decided(row.kind, "rejected")  # type: ignore[arg-type]
    return suggestions.view(db, row)
