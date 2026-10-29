"""user deletion removes meal items that use the user's custom foods

D66 (#131). `meal_item.food_id` is `ON DELETE RESTRICT`, and RESTRICT is checked immediately, so
`DELETE FROM users` failed when any meal (the user's own or a linked user's) used one of the
user's custom foods. Deleting a single food that a meal still uses must keep failing (#34), so the
foreign key stays as it is; instead a BEFORE DELETE trigger on `users` removes the meal items that
reference the user's foods first. The meals and their other items stay.

Expand-only (rule 8): one function and one trigger are added; no column or constraint changes, so
the previous release is unaffected and the downgrade just drops them.

Revision ID: e1a6c3b8d724
Revises: b4d7f1c9e203
Create Date: 2026-10-29 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e1a6c3b8d724"
down_revision: str | Sequence[str] | None = "b4d7f1c9e203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION remove_meal_items_of_deleted_user_foods() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM meal_item
            WHERE food_id IN (SELECT id FROM food WHERE owner_id = OLD.id);
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER users_before_delete_remove_meal_items
        BEFORE DELETE ON users
        FOR EACH ROW EXECUTE FUNCTION remove_meal_items_of_deleted_user_foods()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER users_before_delete_remove_meal_items ON users")
    op.execute("DROP FUNCTION remove_meal_items_of_deleted_user_foods()")
