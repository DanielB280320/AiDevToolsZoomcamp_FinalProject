"""D108 (CLAUDE.md rule 8): `plan.deleted_at` and the `plan_activation` table are expand-only.
Existing rows stay live and have no activation rows; a row written the way the previous release
writes it (no value) is valid; the migration downgrades and upgrades again."""

import uuid

from sqlalchemy import Connection, create_engine, text

from tests.integration.test_user_delete_food_cascade import _alembic, _user

PREVIOUS_HEAD = "d1f6b8c2a935"

_INSERT = (
    "INSERT INTO plan (id, athlete_id, version, source, active, revision, created_by, created_at,"
    " updated_at, plan_no) VALUES (:id, :a, :v, 'custom', false, 0, :a, now(), now(), 1)"
)


def _plan(conn: Connection, athlete: uuid.UUID, version: int) -> None:
    conn.execute(text(_INSERT), {"id": uuid.uuid4(), "a": athlete, "v": version})


def test_existing_rows_stay_null_and_the_previous_release_still_inserts(
    fresh_database_url: str,
) -> None:
    up = _alembic(fresh_database_url, "upgrade", PREVIOUS_HEAD)
    assert up.returncode == 0, up.stderr
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            ana = _user(conn, "a")
            _plan(conn, ana, 1)
        head = _alembic(fresh_database_url, "upgrade", "head")
        assert head.returncode == 0, head.stderr
        with engine.begin() as conn:
            _plan(conn, ana, 2)  # what the previous release writes: neither column
            rows = conn.execute(
                text("SELECT deleted_at, 0 FROM plan WHERE athlete_id = :a"),
                {"a": ana},
            ).all()
            assert [tuple(r) for r in rows] == [(None, 0), (None, 0)]
        down = _alembic(fresh_database_url, "downgrade", PREVIOUS_HEAD)
        assert down.returncode == 0, down.stderr
        again = _alembic(fresh_database_url, "upgrade", "head")
        assert again.returncode == 0, again.stderr
    finally:
        engine.dispose()
