"""`Exercise` (spec §8, F4): the seeded catalog plus users' custom exercises."""

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Uuid,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Fixed enums (spec F4, D47, D17); mirrored by `MuscleGroup` etc. in openapi.yaml.
MUSCLE_GROUPS = (
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
)
EQUIPMENT = (
    "barbell",
    "dumbbell",
    "machine",
    "cable",
    "bodyweight",
    "band",
    "cardio_machine",
    "none",
)
EXERCISE_TYPES = ("strength", "bodyweight", "timed")
REGIONS = ("upper", "lower", "full", "cardio")


class Exercise(Base):
    """A catalog exercise. `owner_id` is null for seed exercises and the creator for custom ones."""

    __tablename__ = "exercise"
    __table_args__ = (
        CheckConstraint(f"muscle_group IN {MUSCLE_GROUPS!r}", name="muscle_group"),
        CheckConstraint(f"equipment IN {EQUIPMENT!r}", name="equipment"),
        CheckConstraint(f"type IN {EXERCISE_TYPES!r}", name="type"),
        CheckConstraint(f"region IN {REGIONS!r}", name="region"),
        CheckConstraint("met BETWEEN 1 AND 20", name="met"),
        CheckConstraint("increment_kg BETWEEN 0 AND 20", name="increment_kg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    muscle_group: Mapped[str] = mapped_column(String(16))
    equipment: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(16))
    met: Mapped[float] = mapped_column(Numeric(4, 1, asdecimal=False))
    increment_kg: Mapped[float] = mapped_column(Numeric(4, 2, asdecimal=False))
    region: Mapped[str] = mapped_column(String(16))
    allows_added_weight: Mapped[bool] = mapped_column(Boolean, server_default=false())
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Names are unique case-insensitively among seed exercises and among one user's own exercises.
Index(
    "uq_exercise_seed_lower_name",
    func.lower(Exercise.name),
    unique=True,
    postgresql_where=Exercise.owner_id.is_(None),
)
Index(
    "uq_exercise_owner_lower_name",
    Exercise.owner_id,
    func.lower(Exercise.name),
    unique=True,
    postgresql_where=Exercise.owner_id.is_not(None),
)
# Backs the name-ordered catalog listing and its keyset cursor.
Index("ix_exercise_lower_name_id", func.lower(Exercise.name), Exercise.id)
