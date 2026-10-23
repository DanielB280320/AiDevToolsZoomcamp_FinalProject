"""add feature_flag

Runtime feature flags (spec §8 `FeatureFlag`, F6, F11.5, §15.2-15.3). Expand-only: a new table,
nothing existing changes, and the previous release simply ignores it. No rows are seeded; a
missing row means the default from `app.config.FEATURE_FLAGS`.

Revision ID: 9c4f2a7e1b30
Revises: 5b8e1d0c7a42
Create Date: 2026-10-22 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4f2a7e1b30"
down_revision: str | Sequence[str] | None = "5b8e1d0c7a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_flag",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=64), nullable=False),
        sa.Column("updated_by", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_feature_flag")),
    )


def downgrade() -> None:
    op.drop_table("feature_flag")
