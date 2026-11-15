"""plan: soft delete and the activation log (History delete / make current, D108)

Expand-only and rollback-compatible (CLAUDE.md rule 8): one nullable column and one new table,
no backfill. The previous release neither reads nor writes them; rows it inserts keep a null
`deleted_at` (live) and have no activation rows. Nothing is dropped.

Revision ID: e2a7c9d1b346
Revises: d1f6b8c2a935
Create Date: 2026-11-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a7c9d1b346"
down_revision: str | Sequence[str] | None = "d1f6b8c2a935"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "plan_activation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_activation_athlete_id", "plan_activation", ["athlete_id"])
    op.create_index("ix_plan_activation_plan_id", "plan_activation", ["plan_id"])


def downgrade() -> None:
    op.drop_table("plan_activation")
    op.drop_column("plan", "deleted_at")
