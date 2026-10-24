"""Onboarding, profile and targets (openapi.yaml, tag Profile)."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, SessionDep, TelemetryDep
from app.schemas.athlete import (
    AthleteProfile,
    AthleteProfileInput,
    OnboardingRequest,
    OnboardingResult,
    ProfileUpdateResult,
    Targets,
)
from app.schemas.problem import Problem
from app.services import athlete
from app.services.clock import ClockDep
from app.services.plans import resolve_athlete

router = APIRouter(prefix="/athletes/{athlete_id}", tags=["Profile"])

_PROBLEM = {"model": Problem}


@router.post(
    "/onboarding",
    operation_id="completeOnboarding",
    status_code=201,
    response_model=OnboardingResult,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 409: _PROBLEM, 422: _PROBLEM},
)
def complete_onboarding(
    athlete_id: str,
    body: OnboardingRequest,
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
) -> OnboardingResult:
    """Store the profile and first body metric, compute targets and create plan version 1 in
    one transaction. `409 already_onboarded` if the athlete already completed it."""
    resolve_athlete(user, athlete_id)
    return athlete.onboard(session, user, body, clock.now(), telemetry)


@router.get(
    "/profile",
    operation_id="getAthleteProfile",
    response_model=AthleteProfile,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM},
)
def get_profile(athlete_id: str, user: CurrentUser, session: SessionDep) -> AthleteProfile:
    return athlete.get_profile(session, resolve_athlete(user, athlete_id))


@router.put(
    "/profile",
    operation_id="updateAthleteProfile",
    response_model=ProfileUpdateResult,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM, 422: _PROBLEM},
)
def update_profile(
    athlete_id: str,
    body: AthleteProfileInput,
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
    telemetry: TelemetryDep,
) -> ProfileUpdateResult:
    """Owner only. Recomputes targets from today when a target-relevant field changed (D46)."""
    resolve_athlete(user, athlete_id)
    return athlete.update_profile(session, user, body, clock.now(), telemetry)


@router.get(
    "/targets",
    operation_id="getTargets",
    response_model=Targets,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM},
)
def get_targets(
    athlete_id: str,
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
    date: Annotated[dt.date | None, Query()] = None,
) -> Targets:
    """Targets valid on `date` (default: today in the athlete's time zone)."""
    owner_id = resolve_athlete(user, athlete_id)
    return athlete.get_targets(session, owner_id, user.timezone, clock.now(), date)
