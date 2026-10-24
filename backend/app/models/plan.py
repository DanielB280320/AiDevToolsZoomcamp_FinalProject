"""Training plan persistence (spec §8, F8): `Plan`, `TrainingDay`, `PlannedExercise`, `PlanChange`.

A plan is an immutable-by-convention *version*: a new plan replaces the active one by becoming
`version = n + 1` while the previous version stays readable (F8.2). History never references
these rows for its targets (set logs snapshot them, CLAUDE.md rule 7). Meal days arrive in M3.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

PLAN_SOURCES = ("generated", "custom")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PROGRESSION_RULES = ("linear", "double", "manual")


class Plan(Base):
    __tablename__ = "plan"
    __table_args__ = (
        CheckConstraint(f"source IN {PLAN_SOURCES!r}", name="source"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("revision >= 0", name="revision"),
        UniqueConstraint("athlete_id", "version", name="uq_plan_athlete_id_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    athlete_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    # Optimistic-concurrency counter for custom-mode edits (D42).
    revision: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    training_days: Mapped[list["TrainingDay"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="TrainingDay.position"
    )


# At most one active version per athlete, enforced by the database.
Index(
    "uq_plan_one_active_per_athlete",
    Plan.athlete_id,
    unique=True,
    postgresql_where=Plan.active.is_(True),
)


class TrainingDay(Base):
    __tablename__ = "training_day"
    __table_args__ = (CheckConstraint(f"weekday IN {WEEKDAYS!r}", name="weekday"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("plan.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[str] = mapped_column(String(3))
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column("order", Integer)
    # Last hand editor (F8); null for generated days.
    edited_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    # F13.2 estimate with the athlete's weight at creation or last edit (0 = not computed).
    planned_kcal: Mapped[int] = mapped_column(Integer, server_default="0", default=0)

    plan: Mapped[Plan] = relationship(back_populates="training_days")
    exercises: Mapped[list["PlannedExercise"]] = relationship(
        back_populates="training_day",
        cascade="all, delete-orphan",
        order_by="PlannedExercise.position",
    )


class PlannedExercise(Base):
    __tablename__ = "planned_exercise"
    __table_args__ = (
        CheckConstraint(f"rule IN {PROGRESSION_RULES!r}", name="rule"),
        CheckConstraint("sets BETWEEN 1 AND 10", name="sets"),
        CheckConstraint(
            "reps_max IS NULL OR reps_min IS NULL OR reps_max >= reps_min", name="reps"
        ),
        CheckConstraint("rest_seconds BETWEEN 0 AND 600", name="rest_seconds"),
        CheckConstraint("increment_kg BETWEEN 0 AND 20", name="increment_kg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    training_day_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("training_day.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("exercise.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column("order", Integer)
    sets: Mapped[int] = mapped_column(Integer)
    reps_min: Mapped[int | None] = mapped_column(Integer)
    reps_max: Mapped[int | None] = mapped_column(Integer)
    target_weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 2, asdecimal=False))
    target_seconds: Mapped[int | None] = mapped_column(Integer)
    rest_seconds: Mapped[int] = mapped_column(Integer, server_default="90")
    rule: Mapped[str] = mapped_column(String(16))
    increment_kg: Mapped[float] = mapped_column(Numeric(4, 2, asdecimal=False))
    deload_enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    planned_kcal: Mapped[int] = mapped_column(Integer, server_default="0", default=0)

    training_day: Mapped[TrainingDay] = relationship(back_populates="exercises")


class PlanChange(Base):
    """Audit trail of a plan: who changed it and when (F8.3). `change` holds a small summary."""

    __tablename__ = "plan_change"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("plan.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    change: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
