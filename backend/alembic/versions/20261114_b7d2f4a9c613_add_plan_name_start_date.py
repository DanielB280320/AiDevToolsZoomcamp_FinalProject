"""plan: optional name and start date

Named plans (spec F8, D105). Expand-only and rollback-compatible (CLAUDE.md rule 8): two nullable
columns with no default. The previous release neither reads nor writes them, so it still creates
and edits plans on this schema; plans it creates simply have no name or start date.

Revision ID: b7d2f4a9c613
Revises: a9c3e7f1b402
Create Date: 2026-11-14 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2f4a9c613"
down_revision: str | Sequence[str] | None = "a9c3e7f1b402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("name", sa.String(length=60), nullable=True))
    op.add_column("plan", sa.Column("start_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("plan", "start_date")
    op.drop_column("plan", "name")
