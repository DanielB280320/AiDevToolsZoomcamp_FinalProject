"""plan: soft delete and re-activation time (History delete / make current, D108)

Expand-only and rollback-compatible (CLAUDE.md rule 8): two nullable columns, no default, no
backfill. The previous release neither reads nor writes them; rows it inserts keep null (not
deleted, never re-activated). Nothing is dropped.

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
    op.add_column("plan", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("plan", "activated_at")
    op.drop_column("plan", "deleted_at")
