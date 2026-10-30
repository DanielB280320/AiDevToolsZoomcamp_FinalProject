# ADR 0011: User deletion vs. shared references: RESTRICT stays, a trigger clears the references

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-30 |
| **Deciders** | Owner (D66), Engineer |
| **Spec** | [F18](../spec.md#f18-data-ownership--must), [§19](../spec.md#19-decisions-log) D66, D69, D70; issues #131, #148, #154 |

## Context

A user's rows can be referenced by other users' rows: a coach edits a linked athlete's plan, or a linked user's meal uses a custom food or meal of the deleted user. Two of these references use `ON DELETE RESTRICT` on purpose, so that deleting one food (`meal_item.food_id`) or one meal (`planned_meal.meal_id`) that is still in use through the API is refused (#34). RESTRICT is checked immediately, so it also fires during the `DELETE FROM users` cascade, before the cascade through the owner's own plan has removed the referencing rows. Account deletion (F18) failed twice for this reason (#131, #154).

## Decision

- References to a user as author or editor (`created_by`, `author_id`, `edited_by`, `decided_by`) become `ON DELETE SET NULL` (D69): the other user's data stays, only the reference is cleared.
- References from a linked user's rows to the deleted user's own food or meal keep `RESTRICT`. A `BEFORE DELETE` trigger on `users` removes the referencing `meal_item` (D66) or `planned_meal` (D70) rows first. The linked user's meal, meal day and other rows stay, and the linked user is notified once per deleted account.
- Migrations are expand-only (rule 8): a function and a trigger are added, no column or constraint changes.

## Alternatives considered

- Change the foreign keys to `ON DELETE CASCADE`: deleting one used food or meal through the API would silently empty other people's plans. Rejected.
- Delete the rows in application code before the user: every other path that deletes a user (scripts, tests, future code) could miss it, and the delete would need to be one transaction with the notification lookup. A trigger holds the rule in one place; the notification still has to be collected in the application before the delete (#45/#50).
- `ON DELETE SET NULL` on the content references: the columns are mandatory and an item without a food or a slot without a meal has no meaning.

## Consequences

- Any new foreign key from content a user can share to another user's content must be reviewed against this rule: set null for authorship, a trigger for content references.
- The trigger runs per deleted user and uses the `owner_id` index on `food` and `meal`.
- The notification for linked users must be computed before the delete, because afterwards the rows are gone.
