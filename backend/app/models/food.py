"""`Food`, `Meal` and `MealItem` (spec §8, F6). Stored in metric: kcal and grams only."""

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

FOOD_SOURCES = ("seed", "custom", "openfoodfacts")
MEAL_SOURCES = ("seed", "custom")
MEAL_SLOTS = ("breakfast", "lunch", "dinner", "snack")
DIET_TAGS = ("vegetarian", "vegan", "pescatarian")
ALLERGENS = ("gluten", "lactose", "nuts", "eggs", "soy", "shellfish", "fish")


def _per_100g() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("kcal_per_100g BETWEEN 0 AND 900", name="kcal"),
        CheckConstraint("protein_g_per_100g BETWEEN 0 AND 100", name="protein"),
        CheckConstraint("carbs_g_per_100g BETWEEN 0 AND 100", name="carbs"),
        CheckConstraint("fat_g_per_100g BETWEEN 0 AND 100", name="fat"),
    )


class Food(Base):
    """A food with macros per 100 g. `owner_id` is null for seed and imported foods."""

    __tablename__ = "food"
    __table_args__ = (
        CheckConstraint(f"source IN {FOOD_SOURCES!r}", name="source"),
        *_per_100g(),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    external_code: Mapped[str | None] = mapped_column(String(14))
    name: Mapped[str] = mapped_column(String(120))
    brand: Mapped[str | None] = mapped_column(String(80))
    kcal_per_100g: Mapped[float] = mapped_column(Numeric(5, 1, asdecimal=False))
    protein_g_per_100g: Mapped[float] = mapped_column(Numeric(4, 1, asdecimal=False))
    carbs_g_per_100g: Mapped[float] = mapped_column(Numeric(4, 1, asdecimal=False))
    fat_g_per_100g: Mapped[float] = mapped_column(Numeric(4, 1, asdecimal=False))
    diet_tags: Mapped[list[str]] = mapped_column(JSONB)
    allergen_tags: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


Index(
    "uq_food_seed_lower_name",
    func.lower(Food.name),
    unique=True,
    postgresql_where=Food.source == "seed",
)
Index(
    "uq_food_external_code",
    Food.external_code,
    unique=True,
    postgresql_where=Food.external_code.is_not(None),
)
Index("ix_food_lower_name_id", func.lower(Food.name), Food.id)


class Meal(Base):
    """A meal: named list of `(food, grams)`; macros are computed, never stored."""

    __tablename__ = "meal"
    __table_args__ = (CheckConstraint(f"source IN {MEAL_SOURCES!r}", name="source"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    slots: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


Index(
    "uq_meal_seed_lower_name",
    func.lower(Meal.name),
    unique=True,
    postgresql_where=Meal.source == "seed",
)
Index("ix_meal_lower_name_id", func.lower(Meal.name), Meal.id)


class MealItem(Base):
    __tablename__ = "meal_item"
    __table_args__ = (CheckConstraint("grams > 0 AND grams <= 2000", name="grams"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("meal.id", ondelete="CASCADE"), index=True
    )
    food_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("food.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column()
    grams: Mapped[float] = mapped_column(Numeric(6, 1, asdecimal=False))


__all__ = ["Food", "Meal", "MealItem"]
