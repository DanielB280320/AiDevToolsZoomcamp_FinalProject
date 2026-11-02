"""session: imported flag, plan and training day optional

CSV import of past workouts (spec F10.5, D89). Expand-only and rollback-compatible (CLAUDE.md
rule 8): a new `imported` column with a server default, and `plan_id` / `training_day_id`
relaxed from NOT NULL to nullable. The previous release never writes a null into them and never
sets `imported`, so it still starts and logs on this schema. The `set_log` target columns were
already nullable (revision e6b1f3a9c2d8); nothing changes there.

Rolling back after an import: the previous release does not know plan-less sessions, so a
day that holds one may answer 500 on the old code until the rows are removed
(`DELETE FROM session WHERE imported`, which cascades to their sets). Rollbacks before any
import are unaffected.

Revision ID: a9c3e7f1b402
Revises: f3b8d1a6c274
Create Date: 2026-11-01 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c3e7f1b402"
down_revision: str | Sequence[str] | None = "f3b8d1a6c274"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "session",
        sa.Column("imported", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.alter_column("session", "plan_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("session", "training_day_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    # Plan-less rows cannot satisfy NOT NULL: drop them first (their sets cascade).
    op.execute("DELETE FROM session WHERE plan_id IS NULL OR training_day_id IS NULL")
    op.alter_column("session", "training_day_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("session", "plan_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("session", "imported")
