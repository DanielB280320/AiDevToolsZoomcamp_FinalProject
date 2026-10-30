"""D71 / #154: deleting a user must not be blocked by `planned_meal.meal_id` (F18.2, F18.6), while
deleting a single meal that a plan still uses keeps failing as in #34. Rows are inserted directly
(the delete endpoint, links and notifications are other issues)."""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.migrations import BACKEND_DIR


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[Engine]:
    built = create_engine(migrated_database_url)
    yield built
    built.dispose()


def _user(conn: Connection, tag: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role, birth_date, units,"
            " timezone, disclaimer_accepted_at, created_at, updated_at) VALUES (:id, :email, 'x',"
            " 'T', 'athlete', '1990-01-01', 'metric', 'UTC', now(), now(), now())"
        ),
        {"id": user_id, "email": f"{tag}-{user_id}@example.com"},
    )
    return user_id


def _meal(conn: Connection, owner: uuid.UUID | None) -> uuid.UUID:
    meal_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO meal (id, owner_id, source, name, slots) VALUES"
            " (:id, :owner, 'custom', :name, '[\"lunch\"]')"
        ),
        {"id": meal_id, "owner": owner, "name": f"m-{meal_id}"},
    )
    return meal_id


def _plan(conn: Connection, athlete: uuid.UUID, meals: list[uuid.UUID]) -> uuid.UUID:
    """A plan for `athlete` with one meal day holding one planned meal per entry of `meals`."""
    plan_id, day_id = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO plan (id, athlete_id, version, source, active, revision, created_at,"
            " updated_at) VALUES (:id, :a, 1, 'custom', true, 0, now(), now())"
        ),
        {"id": plan_id, "a": athlete},
    )
    conn.execute(
        text("INSERT INTO meal_day (id, plan_id, weekday, \"order\") VALUES (:id, :p, 'mon', 0)"),
        {"id": day_id, "p": plan_id},
    )
    for position, meal_id in enumerate(meals):
        conn.execute(
            text(
                'INSERT INTO planned_meal (id, meal_day_id, slot, "order", meal_id, portion_factor)'
                " VALUES (:id, :d, 'lunch', :o, :m, 1)"
            ),
            {"id": uuid.uuid4(), "d": day_id, "o": position, "m": meal_id},
        )
    return day_id


def _count(conn: Connection, sql: str, **params: object) -> int:
    return int(conn.execute(text(sql), params).scalar_one())


def test_deleting_a_user_whose_meals_are_in_their_own_plan_succeeds(engine: Engine) -> None:
    with engine.begin() as conn:
        user = _user(conn, "a")
        bystander = _user(conn, "bystander")
        _plan(conn, user, [_meal(conn, user), _meal(conn, user)])
        other_day = _plan(conn, bystander, [_meal(conn, bystander)])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=user) == 0
        assert _count(conn, "SELECT count(*) FROM meal WHERE owner_id = :u", u=user) == 0
        assert _count(conn, "SELECT count(*) FROM planned_meal") == 1
        assert _count(conn, "SELECT count(*) FROM meal_day WHERE id = :d", d=other_day) == 1


def test_deleting_a_user_removes_only_their_meals_from_a_linked_users_plan(
    engine: Engine,
) -> None:
    with engine.begin() as conn:
        a = _user(conn, "a")
        b = _user(conn, "b")
        a_meal = _meal(conn, a)
        b_meal = _meal(conn, b)
        seed_meal = _meal(conn, None)
        b_day = _plan(conn, b, [b_meal, a_meal, seed_meal, a_meal])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=a) == 0
        assert _count(conn, "SELECT count(*) FROM meal_day WHERE id = :d", d=b_day) == 1
        remaining = set(
            conn.execute(
                text("SELECT meal_id FROM planned_meal WHERE meal_day_id = :d"), {"d": b_day}
            ).scalars()
        )
        assert remaining == {b_meal, seed_meal}
        assert _count(conn, "SELECT count(*) FROM meal WHERE id = :m", m=b_meal) == 1
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=b) == 1


def test_deleting_a_user_leaves_unrelated_planned_meals_untouched(engine: Engine) -> None:
    with engine.begin() as conn:
        a = _user(conn, "a")
        b = _user(conn, "b")
        _plan(conn, b, [_meal(conn, b)])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM planned_meal") == 1


def test_deleting_a_single_meal_still_used_by_a_plan_is_still_refused(engine: Engine) -> None:
    """#34 behaviour: the meal foreign key stays RESTRICT; only a user deletion removes rows."""
    with engine.begin() as conn:
        user = _user(conn, "a")
        meal = _meal(conn, user)
        _plan(conn, user, [meal])
    with (
        pytest.raises(IntegrityError, match="fk_planned_meal_meal_id_meal"),
        engine.begin() as conn,
    ):
        conn.execute(text("DELETE FROM meal WHERE id = :id"), {"id": meal})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM planned_meal WHERE meal_id = :m", m=meal) == 1


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_migration_downgrades_and_upgrades_again_with_existing_data(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as conn:
            user = _user(conn, "a")
            _plan(conn, user, [_meal(conn, user)])
        down = _alembic(migrated_database_url, "downgrade", "-1")
        assert down.returncode == 0, down.stderr
        with engine.connect() as conn:
            triggers = "SELECT count(*) FROM pg_trigger WHERE tgname = :n"
            assert _count(conn, triggers, n="users_before_delete_remove_planned_meals") == 0
            assert _count(conn, "SELECT count(*) FROM planned_meal") == 1
        up = _alembic(migrated_database_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user})
        with engine.connect() as conn:
            assert _count(conn, "SELECT count(*) FROM planned_meal") == 0
    finally:
        engine.dispose()
