"""add coach_profile, coach_link and entitlement

Coach linking (F16, #46). Expand-only (rule 8): three new tables, nothing existing changes, so the
previous release is unaffected and the downgrade just drops them. Partial unique indexes allow one
active link and one pending request per athlete.

Revision ID: c5e9a1d7b246
Revises: e2a7c4b9d516
Create Date: 2026-10-31 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e9a1d7b246"
down_revision: str | Sequence[str] | None = "e2a7c4b9d516"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coach_profile",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("bio", sa.String(length=500), nullable=False),
        sa.Column("discoverable", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_coach_profile_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_coach_profile"),
    )
    op.create_table(
        "coach_link",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("coach_id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'declined', 'ended')",
            name=op.f("ck_coach_link_status"),
        ),
        sa.CheckConstraint("source IN ('request')", name=op.f("ck_coach_link_source")),
        sa.ForeignKeyConstraint(
            ["coach_id"], ["users.id"], name="fk_coach_link_coach_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"], ["users.id"], name="fk_coach_link_athlete_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_coach_link"),
    )
    op.create_index(
        "ix_coach_link_athlete_id_created_at", "coach_link", ["athlete_id", "created_at"]
    )
    op.create_index("ix_coach_link_coach_id_created_at", "coach_link", ["coach_id", "created_at"])
    op.create_index(
        "uq_coach_link_athlete_id_active",
        "coach_link",
        ["athlete_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_coach_link_athlete_id_pending",
        "coach_link",
        ["athlete_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "entitlement",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_entitlement_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name="pk_entitlement"),
    )


def downgrade() -> None:
    op.drop_table("entitlement")
    op.drop_table("coach_link")
    op.drop_table("coach_profile")
