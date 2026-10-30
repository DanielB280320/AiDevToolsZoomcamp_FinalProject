"""user deletion removes planned meals that use the user's meals

D70 (#154). `planned_meal.meal_id` is `ON DELETE RESTRICT`, which is checked immediately, so
`DELETE FROM users` failed when a planned meal (in the user's own plan or a linked user's plan)
pointed at one of the user's meals: the cascade users -> meal reaches the RESTRICT before the
cascade users -> plan -> meal_day -> planned_meal has removed the row. Deleting a single meal that
a plan still uses must keep failing (#34), so the foreign key stays as it is; a BEFORE DELETE
trigger on `users` removes the planned meals that reference the user's meals first. The meal days
and the other planned meals stay. Same approach as D66 / e1a6c3b8d724.

Expand-only (rule 8): one function and one trigger are added; no column or constraint changes, so
the previous release is unaffected and the downgrade just drops them.

Revision ID: a7d2e5c9b148
Revises: c5e8a1d7b362
Create Date: 2026-10-30 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d2e5c9b148"
down_revision: str | Sequence[str] | None = "c5e8a1d7b362"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION remove_planned_meals_of_deleted_user_meals() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM planned_meal
            WHERE meal_id IN (SELECT id FROM meal WHERE owner_id = OLD.id);
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER users_before_delete_remove_planned_meals
        BEFORE DELETE ON users
        FOR EACH ROW EXECUTE FUNCTION remove_planned_meals_of_deleted_user_meals()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER users_before_delete_remove_planned_meals ON users")
    op.execute("DROP FUNCTION remove_planned_meals_of_deleted_user_meals()")
