"""D105 (CLAUDE.md rule 8): `plan.name` and `plan.start_date` are expand-only. A plan written the
way the previous release writes it (without them) stays valid and reads back null; the migration
downgrades and upgrades again."""

import uuid

from sqlalchemy import create_engine, text

from tests.integration.test_user_delete_food_cascade import _alembic, _user

PREVIOUS_HEAD = "a9c3e7f1b402"


def test_old_writes_stay_valid_and_the_migration_round_trips(fresh_database_url: str) -> None:
    up = _alembic(fresh_database_url, "upgrade", PREVIOUS_HEAD)
    assert up.returncode == 0, up.stderr
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "a")
            conn.execute(
                text(
                    "INSERT INTO plan (id, athlete_id, version, source, active, revision,"
                    " created_by, created_at, updated_at)"
                    " VALUES (:id, :a, 1, 'generated', true, 0, :a, now(), now())"
                ),
                {"id": uuid.uuid4(), "a": athlete},
            )
        head = _alembic(fresh_database_url, "upgrade", "head")
        assert head.returncode == 0, head.stderr
        with engine.begin() as conn:
            assert conn.execute(text("SELECT name, start_date FROM plan")).one() == (None, None)
            # What the previous release writes after a rollback: no name, no start date.
            conn.execute(
                text(
                    "INSERT INTO plan (id, athlete_id, version, source, active, revision,"
                    " created_by, created_at, updated_at)"
                    " VALUES (:id, :a, 2, 'custom', false, 1, :a, now(), now())"
                ),
                {"id": uuid.uuid4(), "a": athlete},
            )
            conn.execute(text("UPDATE plan SET name = 'Cut', start_date = '2026-10-01'"))
        down = _alembic(fresh_database_url, "downgrade", PREVIOUS_HEAD)
        assert down.returncode == 0, down.stderr
        again = _alembic(fresh_database_url, "upgrade", "head")
        assert again.returncode == 0, again.stderr
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM plan")).scalar_one() == 2
    finally:
        engine.dispose()
