"""plan: number of the plan within the athlete

Versions are grouped into plans (spec F8, D106). Expand-only and rollback-compatible (CLAUDE.md
rule 8): one nullable integer column with no default. The previous release neither reads nor
writes it; rows it inserts keep null, which readers resolve as "same plan as the preceding
version", except for a `created_new` change, which starts the next plan (same rule as the
backfill below).

Backfill: per athlete in version order, `plan_no` is 1 plus the number of `created_new` changes
on versions 2..n (the version itself included).

Revision ID: c8e3a5b0d724
Revises: b7d2f4a9c613
Create Date: 2026-11-14 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e3a5b0d724"
down_revision: str | Sequence[str] | None = "b7d2f4a9c613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("plan_no", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE plan SET plan_no = numbered.no
        FROM (
            SELECT p.id,
                   1 + SUM(CASE WHEN p.version > 1 AND EXISTS (
                           SELECT 1 FROM plan_change c
                           WHERE c.plan_id = p.id AND c.change ->> 'kind' = 'created_new'
                       ) THEN 1 ELSE 0 END)
                       OVER (PARTITION BY p.athlete_id ORDER BY p.version) AS no
            FROM plan p
        ) AS numbered
        WHERE plan.id = numbered.id
        """
    )
    op.create_check_constraint("plan_no", "plan", "plan_no IS NULL OR plan_no >= 1")


def downgrade() -> None:
    op.drop_constraint("plan_no", "plan", type_="check")
    op.drop_column("plan", "plan_no")
