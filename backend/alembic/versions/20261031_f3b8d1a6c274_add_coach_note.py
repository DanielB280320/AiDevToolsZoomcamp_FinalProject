"""add coach_note

Coach notes on a day, session or exercise (F16, #49). Expand-only (rule 8): one new table and its
indexes, nothing existing changes, so the previous release is unaffected (it never reads or writes
the table) and the downgrade just drops it. The author, the athlete, the session and the exercise
all cascade, so deleting any of them removes the note (F18).

Revision ID: f3b8d1a6c274
Revises: c5e9a1d7b246
Create Date: 2026-10-31 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d1a6c274"
down_revision: str | Sequence[str] | None = "c5e9a1d7b246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coach_note",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("exercise_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('day', 'session', 'exercise')", name="ck_coach_note_scope"),
        sa.CheckConstraint(
            "char_length(text) BETWEEN 1 AND 2000", name="ck_coach_note_text_length"
        ),
        sa.CheckConstraint(
            "(scope = 'day' AND date IS NOT NULL AND session_id IS NULL AND exercise_id IS NULL)"
            " OR (scope = 'session' AND session_id IS NOT NULL AND exercise_id IS NULL)"
            " OR (scope = 'exercise' AND exercise_id IS NOT NULL)",
            name="ck_coach_note_scope_target",
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"], ["users.id"], name="fk_coach_note_athlete_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name="fk_coach_note_author_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["session.id"],
            name="fk_coach_note_session_id_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name="fk_coach_note_exercise_id_exercise",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_coach_note"),
    )
    op.create_index(
        "ix_coach_note_athlete_id_created_at", "coach_note", ["athlete_id", "created_at"]
    )
    op.create_index("ix_coach_note_session_id", "coach_note", ["session_id"])
    op.create_index("ix_coach_note_exercise_id", "coach_note", ["exercise_id"])


def downgrade() -> None:
    op.drop_table("coach_note")
