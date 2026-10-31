"""`/coach/profile`, `/coaches/search` and `/coach-links` (openapi.yaml, tag Coach)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUser, SessionDep, require_role
from app.models import User
from app.schemas import coach as out
from app.schemas.base import NoNul
from app.schemas.problem import Problem
from app.services import coach_links
from app.services.clock import ClockDep

router = APIRouter(tags=["Coach"])

_PROBLEM = {"model": Problem}
CoachUser = Annotated[User, Depends(require_role("coach"))]
AthleteUser = Annotated[User, Depends(require_role("athlete"))]


@router.get(
    "/coach/profile",
    operation_id="getCoachProfile",
    response_model=out.CoachProfile,
    responses={401: _PROBLEM, 403: _PROBLEM},
)
def get_profile(coach: CoachUser, db: SessionDep) -> out.CoachProfile:
    return coach_links.get_profile(db, coach)


@router.put(
    "/coach/profile",
    operation_id="updateCoachProfile",
    response_model=out.CoachProfile,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 422: _PROBLEM},
)
def update_profile(
    body: out.CoachProfileInput, coach: CoachUser, db: SessionDep
) -> out.CoachProfile:
    return coach_links.update_profile(db, coach, body)


@router.get(
    "/coaches/search",
    operation_id="searchCoaches",
    response_model=out.CoachSearchResultList,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM},
)
def search_coaches(
    athlete: AthleteUser,
    db: SessionDep,
    q: Annotated[str, Query(max_length=254), NoNul],
) -> out.CoachSearchResultList:
    return coach_links.search_coaches(db, q)


@router.get(
    "/coach-links",
    operation_id="listCoachLinks",
    response_model=out.CoachLinkList,
    responses={400: _PROBLEM, 401: _PROBLEM},
)
def list_links(
    user: CurrentUser, db: SessionDep, status: out.CoachLinkStatus | None = None
) -> out.CoachLinkList:
    return coach_links.list_links(db, user, status)


@router.post(
    "/coach-links",
    operation_id="requestCoachLink",
    status_code=201,
    response_model=out.CoachLink,
    responses={
        400: _PROBLEM,
        401: _PROBLEM,
        403: _PROBLEM,
        404: _PROBLEM,
        409: _PROBLEM,
        422: _PROBLEM,
    },
)
def request_link(
    body: out.CoachLinkRequest, athlete: AthleteUser, db: SessionDep, clock: ClockDep
) -> out.CoachLink:
    return coach_links.request_link(db, athlete, body.coach_id, clock.now())


_LINK_ERRORS: dict[int | str, dict[str, Any]] = {
    400: _PROBLEM,
    401: _PROBLEM,
    403: _PROBLEM,
    404: _PROBLEM,
    409: _PROBLEM,
}


@router.post(
    "/coach-links/{link_id}/approve",
    operation_id="approveCoachLink",
    response_model=out.CoachLink,
    responses=_LINK_ERRORS,
)
def approve(link_id: uuid.UUID, coach: CoachUser, db: SessionDep, clock: ClockDep) -> out.CoachLink:
    return coach_links.decide(db, coach, link_id, approve=True, now=clock.now())


@router.post(
    "/coach-links/{link_id}/decline",
    operation_id="declineCoachLink",
    response_model=out.CoachLink,
    responses=_LINK_ERRORS,
)
def decline(link_id: uuid.UUID, coach: CoachUser, db: SessionDep, clock: ClockDep) -> out.CoachLink:
    return coach_links.decide(db, coach, link_id, approve=False, now=clock.now())


@router.post(
    "/coach-links/{link_id}/end",
    operation_id="endCoachLink",
    response_model=out.CoachLink,
    responses=_LINK_ERRORS,
)
def end_link(
    link_id: uuid.UUID, user: CurrentUser, db: SessionDep, clock: ClockDep
) -> out.CoachLink:
    return coach_links.end(db, user, link_id, clock.now())
