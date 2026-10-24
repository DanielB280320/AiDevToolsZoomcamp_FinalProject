"""add session table

Training sessions (spec §8, F9). Expand-only: one new table with foreign keys to `users`, `plan`
and `training_day`; nothing existing changes and the previous release ignores it. The unique
constraint on (athlete_id, date) enforces "one session per day".

Revision ID: d5a2c8e7b913
Revises: c3b9f1a2d4e7
Create Date: 2026-10-24 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5a2c8e7b913"
down_revision: str | Sequence[str] | None = "c3b9f1a2d4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("training_day_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("original_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="planned", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion", sa.Numeric(5, 4, asdecimal=False), nullable=True),
        sa.Column("kcal", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'done')", name=op.f("ck_session_status")
        ),
        sa.CheckConstraint(
            "completion IS NULL OR completion BETWEEN 0 AND 1", name=op.f("ck_session_completion")
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["users.id"],
            name=op.f("fk_session_athlete_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], name=op.f("fk_session_plan_id_plan")),
        sa.ForeignKeyConstraint(
            ["training_day_id"],
            ["training_day.id"],
            name=op.f("fk_session_training_day_id_training_day"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session")),
        sa.UniqueConstraint("athlete_id", "date", name="uq_session_athlete_id_date"),
    )
    op.create_index(op.f("ix_session_plan_id"), "session", ["plan_id"], unique=False)
    op.create_index(
        "ix_session_athlete_id_original_date", "session", ["athlete_id", "original_date"]
    )


def downgrade() -> None:
    op.drop_table("session")
