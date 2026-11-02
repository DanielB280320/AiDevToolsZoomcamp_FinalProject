"""#57 (CLAUDE.md rule 8): `session.imported` and the nullable `plan_id` / `training_day_id` are
expand-only. A session written the way the previous release writes it (no `imported`, with a plan
and a training day) stays valid; a plan-less imported session is accepted; the migration
downgrades (dropping imported sessions only) and upgrades again."""

import uuid

from sqlalchemy import Connection, create_engine, text

from tests.integration.test_user_delete_food_cascade import _alembic, _user

PREVIOUS_HEAD = "f3b8d1a6c274"


def _plan_and_day(conn: Connection, athlete: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    plan, day = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO plan (id, athlete_id, version, source, active, revision, created_by,"
            " created_at, updated_at)"
            " VALUES (:id, :a, 1, 'generated', true, 0, :a, now(), now())"
        ),
        {"id": plan, "a": athlete},
    )
    conn.execute(
        text(
            'INSERT INTO training_day (id, plan_id, weekday, name, "order") VALUES (:d, :p,'
            " 'mon', 'Day', 1)"
        ),
        {"d": day, "p": plan},
    )
    return plan, day


def _session(conn: Connection, athlete: uuid.UUID, day: str, plan: object, tday: object) -> None:
    """A row as the previous release writes it: no `imported` column."""
    conn.execute(
        text(
            "INSERT INTO session (id, athlete_id, plan_id, training_day_id, date, status,"
            " created_at) VALUES (:id, :a, :p, :t, :d, 'planned', now())"
        ),
        {"id": uuid.uuid4(), "a": athlete, "p": plan, "t": tday, "d": day},
    )


def test_old_writes_stay_valid_plan_less_rows_are_accepted_and_it_round_trips(
    fresh_database_url: str,
) -> None:
    up = _alembic(fresh_database_url, "upgrade", PREVIOUS_HEAD)
    assert up.returncode == 0, up.stderr
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "a")
            plan, tday = _plan_and_day(conn, athlete)
            _session(conn, athlete, "2026-10-19", plan, tday)
        head = _alembic(fresh_database_url, "upgrade", "head")
        assert head.returncode == 0, head.stderr
        with engine.begin() as conn:
            # What the previous release writes on the new schema (after a rollback).
            _session(conn, athlete, "2026-10-20", plan, tday)
            imported = conn.execute(text("SELECT bool_or(imported) FROM session")).scalar_one()
            assert imported is False  # default for old rows and old writes
            # What the import writes: no plan, no training day.
            _session(conn, athlete, "2026-08-03", None, None)
            conn.execute(text("UPDATE session SET imported = true WHERE plan_id IS NULL"))
        down = _alembic(fresh_database_url, "downgrade", PREVIOUS_HEAD)
        assert down.returncode == 0, down.stderr
        with engine.connect() as conn:
            dates = conn.execute(text("SELECT date::text FROM session ORDER BY date")).scalars()
            assert list(dates) == ["2026-10-19", "2026-10-20"]  # only the imported day is gone
        again = _alembic(fresh_database_url, "upgrade", "head")
        assert again.returncode == 0, again.stderr
    finally:
        engine.dispose()
