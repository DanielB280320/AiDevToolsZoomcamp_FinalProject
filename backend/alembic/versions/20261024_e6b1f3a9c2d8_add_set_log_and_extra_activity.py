"""add set_log and extra_activity

Training logging (spec F10). Expand-only: two new tables; nothing existing changes and the
previous release ignores them. `set_log.planned_exercise_id` is deliberately not a foreign key:
set logs snapshot their targets and must survive plan edits (CLAUDE.md rule 7).

Revision ID: e6b1f3a9c2d8
Revises: d5e8a1b3c7f9
Create Date: 2026-10-24 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6b1f3a9c2d8"
down_revision: str | Sequence[str] | None = "d5e8a1b3c7f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "set_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("planned_exercise_id", sa.Uuid(), nullable=True),
        sa.Column("exercise_id", sa.Uuid(), nullable=False),
        sa.Column("set_no", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("target_reps", sa.Integer(), nullable=True),
        sa.Column("target_weight_kg", sa.Numeric(5, 2, asdecimal=False), nullable=True),
        sa.Column("target_seconds", sa.Integer(), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(6, 2, asdecimal=False), nullable=True),
        sa.Column("seconds", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Numeric(9, 1, asdecimal=False), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("set_no BETWEEN 1 AND 30", name=op.f("ck_set_log_set_no")),
        sa.CheckConstraint(
            "skipped OR reps IS NOT NULL OR seconds IS NOT NULL",
            name=op.f("ck_set_log_performed_has_values"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["session.id"],
            name=op.f("fk_set_log_session_id_session"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name=op.f("fk_set_log_exercise_id_exercise"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_set_log")),
        sa.UniqueConstraint(
            "session_id", "exercise_id", "set_no", name="uq_set_log_session_exercise_set"
        ),
    )
    op.create_index(op.f("ix_set_log_session_id"), "set_log", ["session_id"], unique=False)
    op.create_table(
        "extra_activity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("exercise_id", sa.Uuid(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("kcal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("minutes BETWEEN 1 AND 600", name=op.f("ck_extra_activity_minutes")),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["users.id"],
            name=op.f("fk_extra_activity_athlete_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name=op.f("fk_extra_activity_exercise_id_exercise"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extra_activity")),
    )
    op.create_index(
        "ix_extra_activity_athlete_id_date", "extra_activity", ["athlete_id", "date"], unique=False
    )


def downgrade() -> None:
    op.drop_table("extra_activity")
    op.drop_table("set_log")
