"""add plan_change.author_role

Plan changes record the author's role (athlete / coach) next to the author id (F8.3, #39), so the
trail still says who edited after the author's account is deleted (`author_id` is then null).
Expand-only: one nullable column, backfilled from the author's current role. The previous release
inserts rows without it, which is valid.

Revision ID: b4c8e2f6a931
Revises: d9b4e7a2c158
Create Date: 2026-10-30 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c8e2f6a931"
down_revision: str | Sequence[str] | None = "d9b4e7a2c158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_change", sa.Column("author_role", sa.String(length=7), nullable=True))
    op.execute(
        "UPDATE plan_change c SET author_role = u.role FROM users u WHERE c.author_id = u.id"
    )


def downgrade() -> None:
    op.drop_column("plan_change", "author_role")
