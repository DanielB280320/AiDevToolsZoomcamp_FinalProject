"""`GET /me` and `PATCH /me` (openapi.yaml, tag Me)."""

from fastapi import APIRouter

from app.dependencies import CurrentUser, SessionDep
from app.schemas.problem import Problem
from app.schemas.users import Me, UpdateMeRequest
from app.services import accounts
from app.services.clock import ClockDep

router = APIRouter(prefix="/me", tags=["Me"])

_PROBLEM = {"model": Problem}


@router.get("", operation_id="getMe", response_model=Me, responses={401: _PROBLEM})
def get_me(user: CurrentUser) -> Me:
    return accounts.me_view(user)


@router.patch(
    "",
    operation_id="updateMe",
    response_model=Me,
    responses={400: _PROBLEM, 401: _PROBLEM, 422: _PROBLEM},
)
def update_me(body: UpdateMeRequest, user: CurrentUser, session: SessionDep, clock: ClockDep) -> Me:
    """Partial update of display name, units and time zone."""
    return accounts.me_view(accounts.update_me(session, user, body, clock.now()))
