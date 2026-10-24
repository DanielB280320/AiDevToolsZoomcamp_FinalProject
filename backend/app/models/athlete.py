"""Athlete data (spec §8, F2/F3): `AthleteProfile`, `BodyMetric` and `Targets`.

All values are stored in metric units (CLAUDE.md rule 5). `Targets` rows are never edited when
the profile changes on a later day: a new row with a later `valid_from` is added, so history
keeps the targets it was measured against (rule 7, D46).
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SEXES = ("male", "female", "unspecified")
LIFESTYLES = ("sedentary", "lightly_active", "active", "very_active")
GOALS = ("recomposition", "muscle_gain", "cutting", "maintenance", "wellness")
EXPERIENCES = ("beginner", "intermediate", "advanced")
EQUIPMENT_VARIANTS = ("full_gym", "home_dumbbells", "bodyweight_only")
DIETS = ("omnivore", "vegetarian", "vegan", "pescatarian")
BF_METHODS = ("entered", "navy")
BMR_FORMULAS = ("katch_mcardle", "mifflin_st_jeor")

_JSON = JSON().with_variant(JSONB(), "postgresql")


class AthleteProfile(Base):
    __tablename__ = "athlete_profile"
    __table_args__ = (
        CheckConstraint(f"sex IN {SEXES!r}", name="sex"),
        CheckConstraint(f"lifestyle IN {LIFESTYLES!r}", name="lifestyle"),
        CheckConstraint(f"goal IN {GOALS!r}", name="goal"),
        CheckConstraint(f"experience IN {EXPERIENCES!r}", name="experience"),
        CheckConstraint(f"equipment IN {EQUIPMENT_VARIANTS!r}", name="equipment"),
        CheckConstraint(f"diet IN {DIETS!r}", name="diet"),
        CheckConstraint("height_cm BETWEEN 120 AND 230", name="height_cm"),
        CheckConstraint("days_per_week BETWEEN 2 AND 6", name="days_per_week"),
        CheckConstraint("session_minutes IN (30, 45, 60, 75, 90)", name="session_minutes"),
        CheckConstraint("meals_per_day IN (3, 4, 5)", name="meals_per_day"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sex: Mapped[str] = mapped_column(String(16))
    height_cm: Mapped[float] = mapped_column(Numeric(4, 1, asdecimal=False))
    lifestyle: Mapped[str] = mapped_column(String(16))
    goal: Mapped[str] = mapped_column(String(16))
    experience: Mapped[str] = mapped_column(String(16))
    days_per_week: Mapped[int] = mapped_column(Integer)
    preferred_days: Mapped[list[str]] = mapped_column(_JSON)
    session_minutes: Mapped[int] = mapped_column(Integer)
    equipment: Mapped[str] = mapped_column(String(16))
    avoided_exercise_ids: Mapped[list[str]] = mapped_column(_JSON)
    diet: Mapped[str] = mapped_column(String(16))
    allergies: Mapped[list[str]] = mapped_column(_JSON)
    meals_per_day: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class BodyMetric(Base):
    """One body-metric entry per user and local day (D43: upserts on the natural key)."""

    __tablename__ = "body_metric"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_body_metric_user_id_date"),
        CheckConstraint(f"bf_method IS NULL OR bf_method IN {BF_METHODS!r}", name="bf_method"),
        CheckConstraint("weight_kg IS NULL OR weight_kg BETWEEN 35 AND 300", name="weight_kg"),
        CheckConstraint(
            "body_fat_pct IS NULL OR body_fat_pct BETWEEN 3 AND 60", name="body_fat_pct"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[dt.date] = mapped_column(Date)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 2, asdecimal=False))
    body_fat_pct: Mapped[float | None] = mapped_column(Numeric(4, 1, asdecimal=False))
    neck_cm: Mapped[float | None] = mapped_column(Numeric(4, 1, asdecimal=False))
    waist_cm: Mapped[float | None] = mapped_column(Numeric(4, 1, asdecimal=False))
    hip_cm: Mapped[float | None] = mapped_column(Numeric(4, 1, asdecimal=False))
    bf_method: Mapped[str | None] = mapped_column(String(16))
    body_fat_explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Targets(Base):
    """Calorie and macro targets valid from `valid_from` (athlete local day) until the next row."""

    __tablename__ = "targets"
    __table_args__ = (
        UniqueConstraint("user_id", "valid_from", name="uq_targets_user_id_valid_from"),
        CheckConstraint(f"bmr_formula IN {BMR_FORMULAS!r}", name="bmr_formula"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    valid_from: Mapped[dt.date] = mapped_column(Date)
    bmr_formula: Mapped[str] = mapped_column(String(16))
    bmr_kcal: Mapped[int] = mapped_column(Integer)
    lifestyle_factor: Mapped[float] = mapped_column(Float)
    baseline_kcal: Mapped[int] = mapped_column(Integer)
    planned_exercise_kcal_per_day: Mapped[int] = mapped_column(Integer)
    goal_adjustment_pct: Mapped[float] = mapped_column(Float)
    kcal: Mapped[int] = mapped_column(Integer)
    protein_g: Mapped[float] = mapped_column(Numeric(6, 1, asdecimal=False))
    carbs_g: Mapped[float] = mapped_column(Numeric(6, 1, asdecimal=False))
    fat_g: Mapped[float] = mapped_column(Numeric(6, 1, asdecimal=False))
    target_balance_kcal: Mapped[int] = mapped_column(Integer)
    floor_applied: Mapped[bool] = mapped_column(Boolean)
    floor_kcal: Mapped[int] = mapped_column(Integer)
    carbs_clamped: Mapped[bool] = mapped_column(Boolean)
    weight_used_kg: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False))
    body_fat_pct_used: Mapped[float | None] = mapped_column(Numeric(4, 1, asdecimal=False))
    explanation: Mapped[str] = mapped_column(Text)
    inputs: Mapped[dict[str, Any]] = mapped_column(_JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
