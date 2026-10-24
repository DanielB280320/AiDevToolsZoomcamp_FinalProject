"""Catalog schemas: `ExerciseInput`, `Exercise`, `ExercisePage` (openapi.yaml)."""

import uuid
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.users import UserRef

MuscleGroup = Literal[
    "chest",
    "back",
    "shoulders",
    "biceps",
    "triceps",
    "forearms",
    "core",
    "quads",
    "hamstrings",
    "glutes",
    "calves",
    "full_body",
    "cardio",
]
ExerciseEquipment = Literal[
    "barbell", "dumbbell", "machine", "cable", "bodyweight", "band", "cardio_machine", "none"
]
ExerciseType = Literal["strength", "bodyweight", "timed"]
BodyRegion = Literal["upper", "lower", "full", "cardio"]


class ExerciseInput(RequestModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    muscle_group: MuscleGroup
    equipment: ExerciseEquipment
    type: ExerciseType
    met: Annotated[float, Field(ge=1, le=20)]
    increment_kg: Annotated[float, Field(ge=0, le=20)] = 2.5
    region: BodyRegion
    allows_added_weight: bool = False


class Exercise(ResponseModel):
    id: uuid.UUID
    name: str
    muscle_group: MuscleGroup
    equipment: ExerciseEquipment
    type: ExerciseType
    met: float
    increment_kg: float
    region: BodyRegion
    allows_added_weight: bool
    is_custom: bool
    owner: UserRef | None


class ExercisePage(ResponseModel):
    items: list[Exercise]
    next_cursor: str | None
