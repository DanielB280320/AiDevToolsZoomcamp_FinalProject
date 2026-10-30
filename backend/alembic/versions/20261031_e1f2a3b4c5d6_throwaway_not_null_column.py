"""THROWAWAY (#172 regression demo, never merged): NOT NULL column the previous image does not write.

Revision ID: e1f2a3b4c5d6
Revises: b4c8e2f6a931
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "b4c8e2f6a931"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meal_log", sa.Column("demo_required", sa.Text(), nullable=False, server_default="x"))
    op.alter_column("meal_log", "demo_required", server_default=None)


def downgrade() -> None:
    op.drop_column("meal_log", "demo_required")
