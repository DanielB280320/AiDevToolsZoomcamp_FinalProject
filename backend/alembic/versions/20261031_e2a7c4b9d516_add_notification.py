"""add notification

In-app notifications (F17, #45). Expand-only (rule 8): one new table and its indexes, nothing
existing changes, so the previous release is unaffected (it never writes or reads the table) and
the downgrade just drops it. The partial unique index makes a notification about a suggestion
unique per (user, type, suggestion) (D79.1).

Revision ID: e2a7c4b9d516
Revises: b4c8e2f6a931
Create Date: 2026-10-31 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2a7c4b9d516"
down_revision: str | Sequence[str] | None = "b4c8e2f6a931"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_notification_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification"),
    )
    op.create_index(
        "ix_notification_user_id_created_at_id",
        "notification",
        ["user_id", "created_at", "id"],
    )
    op.create_index(
        "uq_notification_user_id_type_suggestion_id",
        "notification",
        ["user_id", "type", sa.text("(payload ->> 'suggestion_id')")],
        unique=True,
        postgresql_where=sa.text("(payload ->> 'suggestion_id') IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("notification")
