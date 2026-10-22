"""add users and sign_in_failures

F1 accounts: the `User` entity (spec §8) with a case-insensitive unique email, and the failed
sign-in log for the per-email rate limit (F1.6). Expand-only: new tables, nothing existing changes.

Revision ID: 5b8e1d0c7a42
Revises: cf51a3d742d2
Create Date: 2026-10-22 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b8e1d0c7a42"
down_revision: str | Sequence[str] | None = "cf51a3d742d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=60), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("units", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("disclaimer_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('athlete', 'coach')", name=op.f("ck_users_role")),
        sa.CheckConstraint("units IN ('metric', 'imperial')", name=op.f("ck_users_units")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "uq_users_lower_email", "users", [sa.literal_column("lower(email)")], unique=True
    )

    op.create_table(
        "sign_in_failures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email_key", sa.String(length=64), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sign_in_failures")),
    )
    op.create_index(
        "ix_sign_in_failures_email_key_failed_at",
        "sign_in_failures",
        ["email_key", "failed_at"],
    )
    op.create_index("ix_sign_in_failures_failed_at", "sign_in_failures", ["failed_at"])


def downgrade() -> None:
    op.drop_table("sign_in_failures")
    op.drop_table("users")
