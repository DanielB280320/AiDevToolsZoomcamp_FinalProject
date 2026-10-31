"""Body-metric endpoints (openapi.yaml, tag Body): weigh-ins and the recalculation prompt (F14)."""

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

from app.dependencies import OwnerAccess, OwnerOrCoachAccess, SessionDep, TelemetryDep
from app.schemas.body import BodyMetricInput, BodyMetricList, BodyMetricResult
from app.schemas.problem import Problem
from app.services import body, suggestions
from app.services.clock import ClockDep

router = APIRouter(tags=["Body"])

_PROBLEM: dict[str, Any] = {"model": Problem}


@router.get(
    "/athletes/{athlete_id}/body-metrics",
    operation_id="listBodyMetrics",
    response_model=BodyMetricList,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM},
)
def list_body_metrics(
    access: OwnerOrCoachAccess,
    db: SessionDep,
    clock: ClockDep,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: Annotated[dt.date | None, Query()] = None,
) -> BodyMetricList:
    """Entries between `from` and `to` inclusive, oldest first (default: last 90 days).

    The owner or a coach with an active link may read.
    """
    owner = access.athlete
    rows = body.list_metrics(db, owner.id, owner.timezone, clock.now(), from_, to)
    return BodyMetricList(items=[body.metric_view(r) for r in rows])


@router.post(
    "/athletes/{athlete_id}/body-metrics",
    operation_id="logBodyMetric",
    response_model=BodyMetricResult,
    responses={
        201: {"model": BodyMetricResult},
        **{400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM, 422: _PROBLEM},
    },
)
def log_body_metric(
    access: OwnerAccess,
    data: BodyMetricInput,
    response: Response,
    db: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
) -> BodyMetricResult:
    """`201` for a new day, `200` when the day's entry is replaced. Owner only."""
    outcome = body.log_metric(db, access.athlete, data, clock.now(), telemetry)
    response.status_code = 201 if outcome.created else 200
    return BodyMetricResult(
        body_metric=body.metric_view(outcome.metric),
        recalc_suggestion=None if outcome.recalc is None else suggestions.view(db, outcome.recalc),
    )
