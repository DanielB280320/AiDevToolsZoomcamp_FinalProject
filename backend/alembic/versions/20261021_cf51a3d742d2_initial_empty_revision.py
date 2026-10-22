"""initial empty revision

Baseline for the walking skeleton: no tables yet. Later revisions add the spec §8 entities.

Revision ID: cf51a3d742d2
Revises:
Create Date: 2026-10-21 20:27:40.295189
"""

from collections.abc import Sequence

revision: str = "cf51a3d742d2"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
