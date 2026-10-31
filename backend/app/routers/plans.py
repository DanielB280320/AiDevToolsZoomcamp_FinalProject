"""Plan endpoints (openapi.yaml, tag Plan): read, custom-mode edits, regenerate, versions."""

from typing import Annotated, Any

from fastapi import APIRouter, Path

from app.dependencies import OwnerOrCoachAccess, SessionDep
from app.schemas.plans import (
    MealPlanUpdate,
    Plan,
    PlanVersionList,
    RegeneratePlanRequest,
    TrainingPlanUpdate,
)
from app.schemas.problem import Problem
from app.services import plan_edit, plans
from app.services.clock import ClockDep

router = APIRouter(prefix="/athletes/{athlete_id}/plan", tags=["Plan"])

_PROBLEM: dict[str, Any] = {"model": Problem}
_COMMON: dict[int | str, dict[str, Any]] = {400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM}


@router.get(
    "",
    operation_id="getActivePlan",
    response_model=Plan,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM},
)
def get_active_plan(access: OwnerOrCoachAccess, session: SessionDep) -> Plan:
    """The active plan version; 404 `not_onboarded` when the athlete has none yet."""
    return plans.get_active_plan(session, access.athlete.id)


@router.put(
    "/training",
    operation_id="updateTrainingPlan",
    response_model=Plan,
    responses={**_COMMON, 404: _PROBLEM, 409: _PROBLEM, 422: _PROBLEM},
)
def update_training_plan(
    access: OwnerOrCoachAccess,
    body: TrainingPlanUpdate,
    session: SessionDep,
    clock: ClockDep,
) -> Plan:
    """Replace the training template; stores a new `custom` version (F8)."""
    return plan_edit.update_training(session, access.actor, access.athlete.id, body, clock.now())


@router.put(
    "/meals",
    operation_id="updateMealPlan",
    response_model=Plan,
    responses={**_COMMON, 404: _PROBLEM, 409: _PROBLEM, 422: _PROBLEM},
)
def update_meal_plan(
    access: OwnerOrCoachAccess,
    body: MealPlanUpdate,
    session: SessionDep,
    clock: ClockDep,
) -> Plan:
    """Replace the meal template; stores a new `custom` version (F8)."""
    return plan_edit.update_meals(session, access.actor, access.athlete.id, body, clock.now())


@router.post(
    "/regenerate",
    operation_id="regeneratePlan",
    response_model=Plan,
    status_code=201,
    responses={**_COMMON, 404: _PROBLEM, 422: _PROBLEM},
)
def regenerate_plan(
    access: OwnerOrCoachAccess,
    session: SessionDep,
    clock: ClockDep,
    body: RegeneratePlanRequest | None = None,
) -> Plan:
    """A new `generated` version from the current profile and targets (F8.2)."""
    scope = body.scope if body else "all"
    return plan_edit.regenerate(session, access.actor, access.athlete.id, scope, clock.now())


@router.get(
    "/versions",
    operation_id="listPlanVersions",
    response_model=PlanVersionList,
    responses=_COMMON,
)
def list_plan_versions(access: OwnerOrCoachAccess, session: SessionDep) -> PlanVersionList:
    """All versions, newest first."""
    return plan_edit.list_versions(session, access.athlete.id)


@router.get(
    "/versions/{version}",
    operation_id="getPlanVersion",
    response_model=Plan,
    responses={**_COMMON, 404: _PROBLEM},
)
def get_plan_version(
    access: OwnerOrCoachAccess,
    version: Annotated[int, Path(ge=1)],
    session: SessionDep,
) -> Plan:
    """One version, read-only."""
    return plan_edit.get_version(session, access.athlete.id, version)
