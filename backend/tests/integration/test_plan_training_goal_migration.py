"""D107 (CLAUDE.md rule 8): `plan.training_goal` is expand-only. Existing rows stay null (readers
resolve the default); a row written the way the previous release writes it (no value) stays valid;
the check rejects an unknown goal; the migration downgrades and upgrades again."""

import uuid

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.integration.test_user_delete_food_cascade import _alembic, _user

PREVIOUS_HEAD = "c8e3a5b0d724"


_COLUMNS = (
    "id, athlete_id, version, source, active, revision, created_by, created_at, updated_at, plan_no"
)
_VALUES = ":id, :a, :v, 'custom', false, 0, :a, now(), now(), 1"


def _plan(conn: Connection, athlete: uuid.UUID, version: int, goal: str | None = None) -> None:
    params = {"id": uuid.uuid4(), "a": athlete, "v": version, "g": goal}
    if goal is None:  # what the previous release writes
        conn.execute(text(f"INSERT INTO plan ({_COLUMNS}) VALUES ({_VALUES})"), params)  # noqa: S608
    else:
        conn.execute(
            text(f"INSERT INTO plan ({_COLUMNS}, training_goal) VALUES ({_VALUES}, :g)"),  # noqa: S608
            params,
        )


def _goals(conn: Connection, athlete: uuid.UUID) -> list[str | None]:
    rows = conn.execute(
        text("SELECT training_goal FROM plan WHERE athlete_id = :a ORDER BY version"),
        {"a": athlete},
    )
    return [r[0] for r in rows]


def test_existing_rows_stay_null_and_the_column_is_checked(fresh_database_url: str) -> None:
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
            assert _goals(conn, ana) == [None]  # no backfill: readers resolve the default
            _plan(conn, ana, 2)  # what the previous release writes: no goal
            _plan(conn, ana, 3, "strength")
            assert _goals(conn, ana) == [None, None, "strength"]
        with pytest.raises(IntegrityError), engine.begin() as conn:
            _plan(conn, ana, 4, "bulk")
        down = _alembic(fresh_database_url, "downgrade", PREVIOUS_HEAD)
        assert down.returncode == 0, down.stderr
        again = _alembic(fresh_database_url, "upgrade", "head")
        assert again.returncode == 0, again.stderr
        with engine.connect() as conn:
            assert _goals(conn, ana) == [None, None, None]  # dropped and recreated
    finally:
        engine.dispose()
