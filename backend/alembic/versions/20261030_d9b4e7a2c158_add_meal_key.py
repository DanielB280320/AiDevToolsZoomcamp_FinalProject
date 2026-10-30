"""add planned_meal.meal_key and meal_log.meal_key

Stable meal identity across plan versions (D73, #159). Expand-only: two nullable columns, a new
unique index and a CHECK that is valid after the backfill; no column or table is dropped. The old
(athlete, date, slot, slot index) unique index is replaced, because with keys it would reject a
legitimate log after a same-day reorder; `meal_log.slot_index` stays as a deprecated column.

Backfill reproduces the D70 position rule once: both tables get the same deterministic key
md5(athlete | weekday | slot | position in slot), so existing logs keep matching the meals they
matched before, in every plan version.

Revision ID: d9b4e7a2c158
Revises: a7d2e5c9b148
Create Date: 2026-10-30 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9b4e7a2c158"
down_revision: str | Sequence[str] | None = "a7d2e5c9b148"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("planned_meal", sa.Column("meal_key", sa.Uuid(), nullable=True))
    op.add_column("meal_log", sa.Column("meal_key", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE planned_meal pm SET meal_key = md5(
            ranked.athlete_id::text || '|' || ranked.weekday || '|' || ranked.slot || '|'
            || ranked.rank::text)::uuid
        FROM (
            SELECT m.id, p.athlete_id, d.weekday, m.slot,
                   row_number() OVER (PARTITION BY m.meal_day_id, m.slot ORDER BY m."order") - 1
                       AS rank
            FROM planned_meal m
            JOIN meal_day d ON d.id = m.meal_day_id
            JOIN plan p ON p.id = d.plan_id
        ) ranked
        WHERE ranked.id = pm.id
        """
    )
    op.execute(
        """
        UPDATE meal_log SET meal_key = md5(
            athlete_id::text || '|'
            || (ARRAY['mon','tue','wed','thu','fri','sat','sun'])[extract(isodow FROM date)::int]
            || '|' || slot || '|' || slot_index::text)::uuid
        WHERE planned_meal_id IS NOT NULL AND slot IS NOT NULL AND slot_index IS NOT NULL
        """
    )
    # A planned log that cannot be identified (no slot or index) can never match a meal: keep it
    # visible as extra food of its own instead of violating the new rule.
    op.execute(
        "UPDATE meal_log SET meal_key = gen_random_uuid()"
        " WHERE planned_meal_id IS NOT NULL AND meal_key IS NULL"
    )
    op.drop_index("uq_meal_log_athlete_id_date_slot_slot_index", table_name="meal_log")
    op.create_index(
        "uq_meal_log_athlete_id_date_meal_key",
        "meal_log",
        ["athlete_id", "date", "meal_key"],
        unique=True,
        postgresql_where=sa.text("planned_meal_id IS NOT NULL"),
    )
    op.create_check_constraint(
        op.f("ck_meal_log_planned_has_meal_key"),
        "meal_log",
        "planned_meal_id IS NULL OR meal_key IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_meal_log_planned_has_meal_key"), "meal_log", type_="check")
    op.drop_index("uq_meal_log_athlete_id_date_meal_key", table_name="meal_log")
    op.create_index(
        "uq_meal_log_athlete_id_date_slot_slot_index",
        "meal_log",
        ["athlete_id", "date", "slot", "slot_index"],
        unique=True,
        postgresql_where=sa.text("planned_meal_id IS NOT NULL"),
    )
    op.drop_column("meal_log", "meal_key")
    op.drop_column("planned_meal", "meal_key")
