"""add exercise

Exercise catalog (spec §8 `Exercise`, F4). Expand-only: a new table with a foreign key to
`users`; nothing existing changes and the previous release simply ignores it. The seed rows are
loaded by the migration step's seed entry point (F4.1, D50), not here.

Revision ID: a7d3e5f10b64
Revises: 9c4f2a7e1b30
Create Date: 2026-10-24 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d3e5f10b64"
down_revision: str | Sequence[str] | None = "9c4f2a7e1b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MUSCLE_GROUPS = (
    "chest, back, shoulders, biceps, triceps, forearms, core, quads, hamstrings, glutes, "
    "calves, full_body, cardio"
)
EQUIPMENT = "barbell, dumbbell, machine, cable, bodyweight, band, cardio_machine, none"


def _in(column: str, values: str) -> str:
    quoted = ", ".join(f"'{value.strip()}'" for value in values.split(","))
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.create_table(
        "exercise",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("muscle_group", sa.String(length=16), nullable=False),
        sa.Column("equipment", sa.String(length=16), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("met", sa.Numeric(4, 1, asdecimal=False), nullable=False),
        sa.Column("increment_kg", sa.Numeric(4, 2, asdecimal=False), nullable=False),
        sa.Column("region", sa.String(length=16), nullable=False),
        sa.Column("allows_added_weight", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            _in("muscle_group", MUSCLE_GROUPS), name=op.f("ck_exercise_muscle_group")
        ),
        sa.CheckConstraint(_in("equipment", EQUIPMENT), name=op.f("ck_exercise_equipment")),
        sa.CheckConstraint(
            _in("type", "strength, bodyweight, timed"), name=op.f("ck_exercise_type")
        ),
        sa.CheckConstraint(
            _in("region", "upper, lower, full, cardio"), name=op.f("ck_exercise_region")
        ),
        sa.CheckConstraint("met BETWEEN 1 AND 20", name=op.f("ck_exercise_met")),
        sa.CheckConstraint("increment_kg BETWEEN 0 AND 20", name=op.f("ck_exercise_increment_kg")),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_exercise_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exercise")),
    )
    op.create_index(op.f("ix_exercise_owner_id"), "exercise", ["owner_id"], unique=False)
    op.create_index(
        "uq_exercise_seed_lower_name",
        "exercise",
        [sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("owner_id IS NULL"),
    )
    op.create_index(
        "uq_exercise_owner_lower_name",
        "exercise",
        ["owner_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("owner_id IS NOT NULL"),
    )
    op.create_index(
        "ix_exercise_lower_name_id",
        "exercise",
        [sa.literal_column("lower(name)"), "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("exercise")
