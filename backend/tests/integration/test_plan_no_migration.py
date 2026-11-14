"""D106 (CLAUDE.md rule 8): `plan.plan_no` is expand-only. The migration backfills it from the
`created_new` changes; a row written the way the previous release writes it (null) stays valid;
the migration downgrades and upgrades again."""

import json
import uuid

from sqlalchemy import Connection, create_engine, text

from tests.integration.test_user_delete_food_cascade import _alembic, _user

PREVIOUS_HEAD = "b7d2f4a9c613"


def _version(
    conn: Connection, athlete: uuid.UUID, version: int, kind: str | None, *, active: bool = False
) -> None:
    plan_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO plan (id, athlete_id, version, source, active, revision,"
            " created_by, created_at, updated_at)"
            " VALUES (:id, :a, :v, 'custom', :active, 0, :a, now(), now())"
        ),
        {"id": plan_id, "a": athlete, "v": version, "active": active},
    )
    if kind:
        conn.execute(
            text(
                "INSERT INTO plan_change (id, plan_id, author_id, author_role, change, created_at)"
                " VALUES (:id, :p, :a, 'athlete', CAST(:c AS jsonb), now())"
            ),
            {"id": uuid.uuid4(), "p": plan_id, "a": athlete, "c": json.dumps({"kind": kind})},
        )


def _numbers(conn: Connection, athlete: uuid.UUID) -> list[int | None]:
    rows = conn.execute(
        text("SELECT plan_no FROM plan WHERE athlete_id = :a ORDER BY version"), {"a": athlete}
    )
    return [r[0] for r in rows]


def test_backfill_old_writes_and_round_trip(fresh_database_url: str) -> None:
    up = _alembic(fresh_database_url, "upgrade", PREVIOUS_HEAD)
    assert up.returncode == 0, up.stderr
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            ana, bob = _user(conn, "a"), _user(conn, "b")
            kinds = ["created", "training_edited", "created_new", "meals_edited", "created_new"]
            for n, kind in enumerate(kinds, start=1):
                _version(conn, ana, n, kind, active=n == len(kinds))
            _version(conn, bob, 1, "created")  # another athlete numbers independently
            _version(conn, bob, 2, None, active=True)  # a version without a change row
        head = _alembic(fresh_database_url, "upgrade", "head")
        assert head.returncode == 0, head.stderr
        with engine.begin() as conn:
            assert _numbers(conn, ana) == [1, 1, 2, 2, 3]
            assert _numbers(conn, bob) == [1, 1]
            # What the previous release writes after a rollback: no plan number.
            conn.execute(text("UPDATE plan SET active = false WHERE athlete_id = :a"), {"a": ana})
            _version(conn, ana, 6, "training_edited", active=True)
            assert _numbers(conn, ana)[-1] is None
        down = _alembic(fresh_database_url, "downgrade", PREVIOUS_HEAD)
        assert down.returncode == 0, down.stderr
        again = _alembic(fresh_database_url, "upgrade", "head")
        assert again.returncode == 0, again.stderr
        with engine.connect() as conn:
            assert _numbers(conn, ana) == [1, 1, 2, 2, 3, 3]
    finally:
        engine.dispose()
