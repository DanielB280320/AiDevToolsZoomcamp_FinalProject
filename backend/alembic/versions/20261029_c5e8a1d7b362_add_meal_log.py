"""add meal_log and meal_log_item

Meal check-offs and extra food (spec F12, #37). Expand-only: two new tables; nothing existing
changes and the previous release ignores them. `planned_meal_id` is deliberately not a foreign
key (history must survive plan changes). The partial unique index on (athlete, date, planned
meal) makes check-off idempotent.

Revision ID: c5e8a1d7b362
Revises: f3b8d1a5c602
Create Date: 2026-10-29 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e8a1d7b362"
down_revision: str | Sequence[str] | None = "f3b8d1a5c602"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meal_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("planned_meal_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("slot", sa.String(length=9), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('eaten', 'adjusted', 'skipped', 'extra')",
            name=op.f("ck_meal_log_status"),
        ),
        sa.CheckConstraint(
            "slot IS NULL OR slot IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name=op.f("ck_meal_log_slot"),
        ),
        sa.CheckConstraint(
            "(status = 'extra') = (planned_meal_id IS NULL)",
            name=op.f("ck_meal_log_extra_has_no_planned_meal"),
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["users.id"],
            name=op.f("fk_meal_log_athlete_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal_log")),
    )
    op.create_index(
        "uq_meal_log_athlete_id_date_planned_meal_id",
        "meal_log",
        ["athlete_id", "date", "planned_meal_id"],
        unique=True,
        postgresql_where=sa.text("planned_meal_id IS NOT NULL"),
    )
    op.create_index("ix_meal_log_athlete_id_date", "meal_log", ["athlete_id", "date"])

    op.create_table(
        "meal_log_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meal_log_id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("grams", sa.Numeric(6, 1, asdecimal=False), nullable=False),
        sa.CheckConstraint("grams > 0 AND grams <= 2000", name=op.f("ck_meal_log_item_grams")),
        sa.ForeignKeyConstraint(
            ["meal_log_id"],
            ["meal_log.id"],
            name=op.f("fk_meal_log_item_meal_log_id_meal_log"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["food_id"],
            ["food.id"],
            name=op.f("fk_meal_log_item_food_id_food"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal_log_item")),
    )
    op.create_index(
        op.f("ix_meal_log_item_meal_log_id"), "meal_log_item", ["meal_log_id"], unique=False
    )
    op.create_index(op.f("ix_meal_log_item_food_id"), "meal_log_item", ["food_id"], unique=False)


def downgrade() -> None:
    op.drop_table("meal_log_item")
    op.drop_table("meal_log")
