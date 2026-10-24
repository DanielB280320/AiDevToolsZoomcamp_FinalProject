"""add plan tables

Training plan persistence (spec §8, F8): `plan`, `training_day`, `planned_exercise`,
`plan_change`. Expand-only: four new tables with foreign keys to `users` and `exercise`;
nothing existing changes and the previous release ignores them.

Revision ID: c3b9f1a2d4e7
Revises: a7d3e5f10b64
Create Date: 2026-10-24 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3b9f1a2d4e7"
down_revision: str | Sequence[str] | None = "a7d3e5f10b64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('generated', 'custom')", name=op.f("ck_plan_source")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_plan_version")),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_plan_revision")),
        sa.ForeignKeyConstraint(
            ["athlete_id"], ["users.id"], name=op.f("fk_plan_athlete_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_plan_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan")),
        sa.UniqueConstraint("athlete_id", "version", name="uq_plan_athlete_id_version"),
    )
    op.create_index(
        "uq_plan_one_active_per_athlete",
        "plan",
        ["athlete_id"],
        unique=True,
        postgresql_where=sa.text("active IS true"),
    )

    op.create_table(
        "training_day",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("edited_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "weekday IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')",
            name=op.f("ck_training_day_weekday"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plan.id"], name=op.f("fk_training_day_plan_id_plan"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["edited_by"], ["users.id"], name=op.f("fk_training_day_edited_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_day")),
    )
    op.create_index(op.f("ix_training_day_plan_id"), "training_day", ["plan_id"], unique=False)

    op.create_table(
        "planned_exercise",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("training_day_id", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.Uuid(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("sets", sa.Integer(), nullable=False),
        sa.Column("reps_min", sa.Integer(), nullable=True),
        sa.Column("reps_max", sa.Integer(), nullable=True),
        sa.Column("target_weight_kg", sa.Numeric(5, 2, asdecimal=False), nullable=True),
        sa.Column("target_seconds", sa.Integer(), nullable=True),
        sa.Column("rest_seconds", sa.Integer(), server_default="90", nullable=False),
        sa.Column("rule", sa.String(length=16), nullable=False),
        sa.Column("increment_kg", sa.Numeric(4, 2, asdecimal=False), nullable=False),
        sa.Column("deload_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "rule IN ('linear', 'double', 'manual')", name=op.f("ck_planned_exercise_rule")
        ),
        sa.CheckConstraint("sets BETWEEN 1 AND 10", name=op.f("ck_planned_exercise_sets")),
        sa.CheckConstraint(
            "reps_max IS NULL OR reps_min IS NULL OR reps_max >= reps_min",
            name=op.f("ck_planned_exercise_reps"),
        ),
        sa.CheckConstraint(
            "rest_seconds BETWEEN 0 AND 600", name=op.f("ck_planned_exercise_rest_seconds")
        ),
        sa.CheckConstraint(
            "increment_kg BETWEEN 0 AND 20", name=op.f("ck_planned_exercise_increment_kg")
        ),
        sa.ForeignKeyConstraint(
            ["training_day_id"],
            ["training_day.id"],
            name=op.f("fk_planned_exercise_training_day_id_training_day"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name=op.f("fk_planned_exercise_exercise_id_exercise"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_exercise")),
    )
    op.create_index(
        op.f("ix_planned_exercise_training_day_id"),
        "planned_exercise",
        ["training_day_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_planned_exercise_exercise_id"), "planned_exercise", ["exercise_id"], unique=False
    )

    op.create_table(
        "plan_change",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column(
            "change",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plan.id"], name=op.f("fk_plan_change_plan_id_plan"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_plan_change_author_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_change")),
    )
    op.create_index(op.f("ix_plan_change_plan_id"), "plan_change", ["plan_id"], unique=False)


def downgrade() -> None:
    op.drop_table("plan_change")
    op.drop_table("planned_exercise")
    op.drop_table("training_day")
    op.drop_table("plan")
