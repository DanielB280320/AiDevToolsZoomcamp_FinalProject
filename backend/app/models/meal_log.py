"""Meal logs (spec §8, F12): what an athlete ate on a day.

A planned meal is checked off at most once per (athlete, date, meal key): the partial unique
index is what makes the check-off idempotent under concurrent requests (F12.3). Every plan
version gives its planned meals new ids, so the log carries `planned_meal.meal_key`, the identity
that plan versions copy forward (D73), and not a position. `planned_meal_id` is a plain id,
not a foreign key, so replacing the plan never rewrites history (CLAUDE.md rule 7); `eaten` logs
store the grams that were planned at the time. Quantities are grams, stored metric.
"""

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

MEAL_LOG_STATUSES = ("eaten", "adjusted", "skipped", "extra")


class MealLog(Base):
    __tablename__ = "meal_log"
    __table_args__ = (
        CheckConstraint(f"status IN {MEAL_LOG_STATUSES!r}", name="status"),
        CheckConstraint(
            "slot IS NULL OR slot IN ('breakfast', 'lunch', 'dinner', 'snack')", name="slot"
        ),
        CheckConstraint(
            "(status = 'extra') = (planned_meal_id IS NULL)", name="extra_has_no_planned_meal"
        ),
        CheckConstraint(
            "planned_meal_id IS NULL OR meal_key IS NOT NULL", name="planned_has_meal_key"
        ),
        Index(
            "uq_meal_log_athlete_id_date_meal_key",
            "athlete_id",
            "date",
            "meal_key",
            unique=True,
            postgresql_where=text("planned_meal_id IS NOT NULL"),
        ),
        Index("ix_meal_log_athlete_id_date", "athlete_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    athlete_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    # Calendar day in the athlete's time zone (not an instant).
    date: Mapped[dt.date] = mapped_column(Date)
    planned_meal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(8))
    slot: Mapped[str | None] = mapped_column(String(9))
    # `planned_meal.meal_key` of the meal this log was made for; null for extra food (D73).
    meal_key: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # Deprecated by D73 (position among the slot's meals, D70); no longer written or read.
    slot_index: Mapped[int | None] = mapped_column(Integer)
    logged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class MealLogItem(Base):
    """A food eaten, in grams. Deleting a food removes the item, never blocks the delete."""

    __tablename__ = "meal_log_item"
    __table_args__ = (CheckConstraint("grams > 0 AND grams <= 2000", name="grams"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meal_log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("meal_log.id", ondelete="CASCADE"), index=True
    )
    food_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("food.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    grams: Mapped[float] = mapped_column(Numeric(6, 1, asdecimal=False))
