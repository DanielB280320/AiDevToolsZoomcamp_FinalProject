"""#39 (CLAUDE.md rule 8): `plan_change.author_role` is an expand-only column. Rows written before
it existed are backfilled from the author's role, rows written by the previous release (no role)
stay valid, and the migration downgrades and upgrades again."""

import uuid

from sqlalchemy import Connection, create_engine, text

from tests.integration.test_user_delete_food_cascade import _alembic, _user

PREVIOUS_HEAD = "d9b4e7a2c158"


def _insert_change(conn: Connection, plan: uuid.UUID, author: uuid.UUID) -> uuid.UUID:
    """A row as the previous release writes it: no `author_role`."""
    change_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO plan_change (id, plan_id, author_id, change, created_at)"
            ' VALUES (:id, :p, :a, \'{"kind": "created"}\', now())'
        ),
        {"id": change_id, "p": plan, "a": author},
    )
    return change_id


def test_author_role_is_backfilled_and_the_previous_release_can_still_insert(
    fresh_database_url: str,
) -> None:
    up = _alembic(fresh_database_url, "upgrade", PREVIOUS_HEAD)
    assert up.returncode == 0, up.stderr
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "a")
            plan = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO plan (id, athlete_id, version, source, active, revision,"
                    " created_by, created_at, updated_at)"
                    " VALUES (:id, :a, 1, 'generated', true, 0, :a, now(), now())"
                ),
                {"id": plan, "a": athlete},
            )
            old = _insert_change(conn, plan, athlete)
        head = _alembic(fresh_database_url, "upgrade", "head")
        assert head.returncode == 0, head.stderr
        with engine.begin() as conn:
            role = conn.execute(
                text("SELECT author_role FROM plan_change WHERE id = :i"), {"i": old}
            ).scalar_one()
            assert role == "athlete"  # backfilled from users.role
            # What the previous release writes after a rollback: no author_role.
            newer = _insert_change(conn, plan, athlete)
            assert (
                conn.execute(
                    text("SELECT author_role FROM plan_change WHERE id = :i"), {"i": newer}
                ).scalar_one()
                is None
            )
        down = _alembic(fresh_database_url, "downgrade", PREVIOUS_HEAD)
        assert down.returncode == 0, down.stderr
        again = _alembic(fresh_database_url, "upgrade", "head")
        assert again.returncode == 0, again.stderr
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM plan_change")).scalar_one() == 2
    finally:
        engine.dispose()
