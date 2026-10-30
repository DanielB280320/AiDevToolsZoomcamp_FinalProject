"""add planned_meal.meal_key and meal_log.meal_key

Stable meal identity across plan versions (D73, #159). Expand-only: two nullable columns, a new
unique index and a CHECK that is valid after the backfill; no column or table is dropped. The old
(athlete, date, slot, slot index) unique index is replaced, because with keys it would reject a
legitimate log after a same-day reorder; `meal_log.slot_index` stays as a deprecated column.

Rollback safety (rule 8): the previous release runs on this schema after a rollback. It writes
planned_meal and planned meal_log rows without `meal_key`, so BEFORE INSERT OR UPDATE triggers
fill a missing key with the same formula as the backfill (the D70 position rule); the CHECK then
holds for both releases, and a log and a meal written by the old release get the same key. The
new code keeps writing `meal_log.slot_index` so the old release still matches new logs.

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
    op.execute(
        """
        CREATE FUNCTION meal_log_fill_meal_key() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.planned_meal_id IS NOT NULL AND NEW.meal_key IS NULL THEN
                IF NEW.slot IS NULL OR NEW.slot_index IS NULL THEN
                    NEW.meal_key := gen_random_uuid();
                ELSE
                    NEW.meal_key := md5(
                        NEW.athlete_id::text || '|'
                        || (ARRAY['mon','tue','wed','thu','fri','sat','sun'])[
                            extract(isodow FROM NEW.date)::int]
                        || '|' || NEW.slot || '|' || NEW.slot_index::text)::uuid;
                END IF;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER meal_log_fill_meal_key BEFORE INSERT OR UPDATE ON meal_log"
        " FOR EACH ROW EXECUTE FUNCTION meal_log_fill_meal_key()"
    )
    op.execute(
        """
        CREATE FUNCTION planned_meal_fill_meal_key() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.meal_key IS NULL THEN
                NEW.meal_key := md5(
                    (SELECT p.athlete_id::text || '|' || d.weekday
                     FROM meal_day d JOIN plan p ON p.id = d.plan_id WHERE d.id = NEW.meal_day_id)
                    || '|' || NEW.slot || '|' || (
                        SELECT count(*) FROM planned_meal o
                        WHERE o.meal_day_id = NEW.meal_day_id AND o.slot = NEW.slot
                          AND o."order" < NEW."order" AND o.id <> NEW.id)::text)::uuid;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER planned_meal_fill_meal_key BEFORE INSERT OR UPDATE ON planned_meal"
        " FOR EACH ROW EXECUTE FUNCTION planned_meal_fill_meal_key()"
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
    op.execute("DROP TRIGGER planned_meal_fill_meal_key ON planned_meal")
    op.execute("DROP FUNCTION planned_meal_fill_meal_key()")
    op.execute("DROP TRIGGER meal_log_fill_meal_key ON meal_log")
    op.execute("DROP FUNCTION meal_log_fill_meal_key()")
    # Positions can repeat after same-day edits; the old unique index needs distinct ones. A
    # later duplicate loses its index (the old release then shows it as extra food, visible).
    op.execute(
        """
        UPDATE meal_log SET slot_index = NULL WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY athlete_id, date, slot, slot_index ORDER BY logged_at, id) AS n
                FROM meal_log WHERE planned_meal_id IS NOT NULL AND slot_index IS NOT NULL
            ) d WHERE d.n > 1
        )
        """
    )
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
