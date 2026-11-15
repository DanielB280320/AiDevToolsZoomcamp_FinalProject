"""plan: training goal (goal-driven progression, D107)

Expand-only and rollback-compatible (CLAUDE.md rule 8): one nullable column with no default and a
check that allows null. The previous release neither reads nor writes it; rows it inserts keep
null, which readers resolve with the default derived from the athlete's profile goal. No backfill:
existing plans keep resolving through that default. Nothing is dropped: the per-exercise
progression rule, increment and deload columns stay.

Revision ID: d1f6b8c2a935
Revises: c8e3a5b0d724
Create Date: 2026-11-15 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1f6b8c2a935"
down_revision: str | Sequence[str] | None = "c8e3a5b0d724"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GOALS = ("strength", "hypertrophy", "endurance", "maintenance", "cutting")


def upgrade() -> None:
    op.add_column("plan", sa.Column("training_goal", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        "training_goal", "plan", f"training_goal IS NULL OR training_goal IN {GOALS!r}"
    )


def downgrade() -> None:
    op.drop_constraint("training_goal", "plan", type_="check")
    op.drop_column("plan", "training_goal")
