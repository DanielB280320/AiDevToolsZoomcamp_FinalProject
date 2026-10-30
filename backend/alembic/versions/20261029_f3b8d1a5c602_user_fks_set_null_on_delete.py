"""user-referencing author/editor/decider columns no longer block user deletion

D69 (#148). Five foreign keys to `users.id` had no ON DELETE rule, so `DELETE FROM users` failed
once a plan, plan change, edited day or decided suggestion pointed at the user (F18.2). They become
`ON DELETE SET NULL`: the athlete's data stays when a linked coach deletes their account, and the
reference to the deleted user is removed. `plan.created_by` and `plan_change.author_id` were NOT
NULL and are relaxed to nullable (expand-only: the previous release always writes a value and
`created_by` reading is the only consumer, which the API now returns as null).

Downgrade restores the old foreign keys; rows whose author was deleted are removed from
`plan_change` and cannot be restored on `plan.created_by`, so that column is set to the plan's
athlete before NOT NULL is re-applied.

Revision ID: f3b8d1a5c602
Revises: e1a6c3b8d724
Create Date: 2026-10-29 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3b8d1a5c602"
down_revision: str | Sequence[str] | None = "e1a6c3b8d724"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column)
_COLUMNS = (
    ("plan", "created_by"),
    ("plan_change", "author_id"),
    ("training_day", "edited_by"),
    ("meal_day", "edited_by"),
    ("suggestion", "decided_by"),
)


def _recreate(table: str, column: str, ondelete: str | None) -> None:
    name = f"fk_{table}_{column}_users"
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, "users", [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    op.alter_column("plan", "created_by", nullable=True)
    op.alter_column("plan_change", "author_id", nullable=True)
    for table, column in _COLUMNS:
        _recreate(table, column, "SET NULL")


def downgrade() -> None:
    for table, column in _COLUMNS:
        _recreate(table, column, None)
    op.execute("UPDATE plan SET created_by = athlete_id WHERE created_by IS NULL")
    op.execute("DELETE FROM plan_change WHERE author_id IS NULL")
    op.alter_column("plan", "created_by", nullable=False)
    op.alter_column("plan_change", "author_id", nullable=False)
