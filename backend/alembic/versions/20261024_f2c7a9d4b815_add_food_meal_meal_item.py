"""add food, meal and meal_item

Food library and meals (spec §8, F6). Expand-only: three new tables (foreign keys to `users`,
and `meal_item` to `meal` and `food`); nothing existing changes and the previous release simply
ignores them. Seed rows are loaded by the migration step's seed entry point (D50), not here.

Revision ID: f2c7a9d4b815
Revises: e6b1f3a9c2d8
Create Date: 2026-10-24 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2c7a9d4b815"
down_revision: str | Sequence[str] | None = "e6b1f3a9c2d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "food",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_code", sa.String(length=14), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("brand", sa.String(length=80), nullable=True),
        sa.Column("kcal_per_100g", sa.Numeric(5, 1, asdecimal=False), nullable=False),
        sa.Column("protein_g_per_100g", sa.Numeric(4, 1, asdecimal=False), nullable=False),
        sa.Column("carbs_g_per_100g", sa.Numeric(4, 1, asdecimal=False), nullable=False),
        sa.Column("fat_g_per_100g", sa.Numeric(4, 1, asdecimal=False), nullable=False),
        sa.Column("diet_tags", postgresql.JSONB(), nullable=False),
        sa.Column("allergen_tags", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('seed', 'custom', 'openfoodfacts')", name=op.f("ck_food_source")
        ),
        sa.CheckConstraint("kcal_per_100g BETWEEN 0 AND 900", name=op.f("ck_food_kcal")),
        sa.CheckConstraint("protein_g_per_100g BETWEEN 0 AND 100", name=op.f("ck_food_protein")),
        sa.CheckConstraint("carbs_g_per_100g BETWEEN 0 AND 100", name=op.f("ck_food_carbs")),
        sa.CheckConstraint("fat_g_per_100g BETWEEN 0 AND 100", name=op.f("ck_food_fat")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_food_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_food")),
    )
    op.create_index(op.f("ix_food_owner_id"), "food", ["owner_id"], unique=False)
    op.create_index(
        "uq_food_seed_lower_name",
        "food",
        [sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("source = 'seed'"),
    )
    op.create_index(
        "uq_food_external_code",
        "food",
        ["external_code"],
        unique=True,
        postgresql_where=sa.text("external_code IS NOT NULL"),
    )
    op.create_index(
        "ix_food_lower_name_id", "food", [sa.literal_column("lower(name)"), "id"], unique=False
    )

    op.create_table(
        "meal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slots", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("source IN ('seed', 'custom')", name=op.f("ck_meal_source")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_meal_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal")),
    )
    op.create_index(op.f("ix_meal_owner_id"), "meal", ["owner_id"], unique=False)
    op.create_index(
        "uq_meal_seed_lower_name",
        "meal",
        [sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("source = 'seed'"),
    )
    op.create_index(
        "ix_meal_lower_name_id", "meal", [sa.literal_column("lower(name)"), "id"], unique=False
    )

    op.create_table(
        "meal_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meal_id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("grams", sa.Numeric(6, 1, asdecimal=False), nullable=False),
        sa.CheckConstraint("grams > 0 AND grams <= 2000", name=op.f("ck_meal_item_grams")),
        sa.ForeignKeyConstraint(
            ["meal_id"], ["meal.id"], name=op.f("fk_meal_item_meal_id_meal"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["food_id"], ["food.id"], name=op.f("fk_meal_item_food_id_food"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meal_item")),
    )
    op.create_index(op.f("ix_meal_item_meal_id"), "meal_item", ["meal_id"], unique=False)
    op.create_index(op.f("ix_meal_item_food_id"), "meal_item", ["food_id"], unique=False)


def downgrade() -> None:
    op.drop_table("meal_item")
    op.drop_table("meal")
    op.drop_table("food")
