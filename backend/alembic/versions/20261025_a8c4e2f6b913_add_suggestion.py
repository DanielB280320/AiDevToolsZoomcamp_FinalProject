"""add suggestion

Suggestions awaiting accept/reject (spec F11, #85). Expand-only: one new table; nothing
existing changes and the previous release ignores it. `planned_exercise_id` is deliberately not
a foreign key (history survives plan edits, CLAUDE.md rule 7).

Revision ID: a8c4e2f6b913
Revises: f2c7a9d4b815
Create Date: 2026-10-25 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8c4e2f6b913"
down_revision: str | Sequence[str] | None = "f2c7a9d4b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "suggestion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("rule", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("inputs", json_type, nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("planned_exercise_id", sa.Uuid(), nullable=True),
        sa.Column("exercise_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('progression', 'calories', 'recalc')", name=op.f("ck_suggestion_kind")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')", name=op.f("ck_suggestion_status")
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["users.id"],
            name=op.f("fk_suggestion_athlete_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["session.id"],
            name=op.f("fk_suggestion_session_id_session"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name=op.f("fk_suggestion_exercise_id_exercise"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_suggestion_decided_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suggestion")),
    )
    op.create_index(
        "ix_suggestion_athlete_id_status_created_at",
        "suggestion",
        ["athlete_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_suggestion_session_id_status", "suggestion", ["session_id", "status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_suggestion_session_id_status", table_name="suggestion")
    op.drop_index("ix_suggestion_athlete_id_status_created_at", table_name="suggestion")
    op.drop_table("suggestion")
