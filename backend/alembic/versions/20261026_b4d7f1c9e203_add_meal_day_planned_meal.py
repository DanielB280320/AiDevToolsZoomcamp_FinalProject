"""add meal_day and planned_meal

Meal plan of a plan version (spec F7, #36). Expand-only: two new tables; nothing existing
changes and the previous release ignores them. A planned meal references the shared `meal`
row (RESTRICT, so a meal in use cannot disappear under a plan).

Revision ID: b4d7f1c9e203
Revises: a8c4e2f6b913
Create Date: 2026-10-26 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d7f1c9e203"
down_revision: str | Sequence[str] | None = "a8c4e2f6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meal_day",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.String(length=3), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("edited_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "weekday IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')",
            name=op.f("ck_meal_day_weekday"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plan.id"], name=op.f("fk_meal_day_plan_id_plan"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["edited_by"], ["users.id"], name=op.f("fk_meal_day_edited_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal_day")),
        sa.UniqueConstraint("plan_id", "weekday", name="uq_meal_day_plan_id_weekday"),
    )
    op.create_index(op.f("ix_meal_day_plan_id"), "meal_day", ["plan_id"], unique=False)

    op.create_table(
        "planned_meal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meal_day_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.String(length=9), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("meal_id", sa.Uuid(), nullable=False),
        sa.Column("portion_factor", sa.Numeric(4, 2, asdecimal=False), nullable=False),
        sa.CheckConstraint(
            "slot IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name=op.f("ck_planned_meal_slot"),
        ),
        sa.CheckConstraint(
            "portion_factor > 0 AND portion_factor <= 3",
            name=op.f("ck_planned_meal_portion_factor"),
        ),
        sa.ForeignKeyConstraint(
            ["meal_day_id"],
            ["meal_day.id"],
            name=op.f("fk_planned_meal_meal_day_id_meal_day"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["meal_id"],
            ["meal.id"],
            name=op.f("fk_planned_meal_meal_id_meal"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_meal")),
    )
    op.create_index(
        op.f("ix_planned_meal_meal_day_id"), "planned_meal", ["meal_day_id"], unique=False
    )
    op.create_index(op.f("ix_planned_meal_meal_id"), "planned_meal", ["meal_id"], unique=False)


def downgrade() -> None:
    op.drop_table("planned_meal")
    op.drop_table("meal_day")
