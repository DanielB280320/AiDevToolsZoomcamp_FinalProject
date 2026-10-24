"""`GET /exercises` and `POST /exercises` (openapi.yaml, tag Catalog)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, SessionDep
from app.schemas.exercises import (
    BodyRegion,
    Exercise,
    ExerciseEquipment,
    ExerciseInput,
    ExercisePage,
    ExerciseType,
    MuscleGroup,
)
from app.schemas.problem import Problem
from app.services import exercises

router = APIRouter(prefix="/exercises", tags=["Catalog"])

_PROBLEM = {"model": Problem}


@router.get(
    "",
    operation_id="listExercises",
    response_model=ExercisePage,
    responses={400: _PROBLEM, 401: _PROBLEM},
)
def list_exercises(
    user: CurrentUser,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    muscle_group: MuscleGroup | None = None,
    equipment: ExerciseEquipment | None = None,
    type: ExerciseType | None = None,
    region: BodyRegion | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> ExercisePage:
    """Seed and visible custom exercises, ordered by name; filters combine with AND."""
    return exercises.list_exercises(
        session,
        user,
        q=q,
        muscle_group=muscle_group,
        equipment=equipment,
        type_=type,
        region=region,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "",
    operation_id="createExercise",
    response_model=Exercise,
    status_code=201,
    responses={400: _PROBLEM, 401: _PROBLEM, 409: _PROBLEM, 422: _PROBLEM},
)
def create_exercise(body: ExerciseInput, user: CurrentUser, session: SessionDep) -> Exercise:
    """Create a custom exercise owned by the caller."""
    return exercises.create_exercise(session, user, body)
