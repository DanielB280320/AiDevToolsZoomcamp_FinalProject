"""`GET /athletes/{athlete_id}/plan` (openapi.yaml, tag Plan)."""

from fastapi import APIRouter

from app.dependencies import CurrentUser, SessionDep
from app.schemas.plans import Plan
from app.schemas.problem import Problem
from app.services import plans

router = APIRouter(prefix="/athletes/{athlete_id}/plan", tags=["Plan"])

_PROBLEM = {"model": Problem}


@router.get(
    "",
    operation_id="getActivePlan",
    response_model=Plan,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM},
)
def get_active_plan(athlete_id: str, user: CurrentUser, session: SessionDep) -> Plan:
    """The active plan version; 404 `not_onboarded` when the athlete has none yet."""
    return plans.get_active_plan(session, plans.resolve_athlete(user, athlete_id))
