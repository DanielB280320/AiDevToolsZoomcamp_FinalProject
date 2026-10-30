"""D66 / #131: deleting a user must not be blocked by `meal_item.food_id` (F18.2, F18.4), while
deleting a single used food keeps failing as in #34. Rows are inserted directly (the delete
endpoint, links and notifications are other issues)."""

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


def _food(conn: Connection, owner: uuid.UUID | None, source: str = "custom") -> uuid.UUID:
    food_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO food (id, owner_id, source, name, kcal_per_100g, protein_g_per_100g,"
            " carbs_g_per_100g, fat_g_per_100g, diet_tags, allergen_tags) VALUES (:id, :owner,"
            " :source, :name, 100, 10, 10, 10, '[]', '[]')"
        ),
        {"id": food_id, "owner": owner, "source": source, "name": f"f-{food_id}"},
    )
    return food_id


def _meal(conn: Connection, owner: uuid.UUID, items: list[uuid.UUID]) -> uuid.UUID:
    meal_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO meal (id, owner_id, source, name, slots) VALUES"
            " (:id, :owner, 'custom', :name, '[\"lunch\"]')"
        ),
        {"id": meal_id, "owner": owner, "name": f"m-{meal_id}"},
    )
    for position, food_id in enumerate(items):
        conn.execute(
            text(
                "INSERT INTO meal_item (id, meal_id, food_id, position, grams)"
                " VALUES (:id, :meal, :food, :pos, 100)"
            ),
            {"id": uuid.uuid4(), "meal": meal_id, "food": food_id, "pos": position},
        )
    return meal_id


def _count(conn: Connection, sql: str, **params: object) -> int:
    return int(conn.execute(text(sql), params).scalar_one())


def test_deleting_a_user_with_their_own_food_in_their_own_meal_succeeds(engine: Engine) -> None:
    with engine.begin() as conn:
        user = _user(conn, "a")
        other = _user(conn, "bystander")
        food = _food(conn, user)
        _meal(conn, user, [food])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=user) == 0
        assert _count(conn, "SELECT count(*) FROM food WHERE owner_id = :u", u=user) == 0
        assert _count(conn, "SELECT count(*) FROM meal WHERE owner_id = :u", u=user) == 0
        assert _count(conn, "SELECT count(*) FROM meal_item WHERE food_id = :f", f=food) == 0
        assert _count(conn, "SELECT count(*) FROM meal_item") == 0
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=other) == 1


def test_deleting_a_user_removes_only_the_items_using_their_food_from_another_users_meal(
    engine: Engine,
) -> None:
    with engine.begin() as conn:
        a = _user(conn, "a")
        b = _user(conn, "b")
        a_food = _food(conn, a)
        b_food = _food(conn, b)
        seed_food = _food(conn, None, source="seed")
        b_meal = _meal(conn, b, [b_food, a_food, seed_food, a_food])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=a) == 0
        assert _count(conn, "SELECT count(*) FROM meal WHERE id = :m", m=b_meal) == 1
        remaining = set(
            conn.execute(
                text("SELECT food_id FROM meal_item WHERE meal_id = :m"), {"m": b_meal}
            ).scalars()
        )
        assert remaining == {b_food, seed_food}
        assert _count(conn, "SELECT count(*) FROM food WHERE id = :f", f=b_food) == 1


def test_deleting_a_user_leaves_unrelated_meal_items_untouched(engine: Engine) -> None:
    with engine.begin() as conn:
        a = _user(conn, "a")
        b = _user(conn, "b")
        b_food = _food(conn, b)
        b_meal = _meal(conn, b, [b_food])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM meal_item WHERE meal_id = :m", m=b_meal) == 1


def test_deleting_a_single_food_still_used_by_a_meal_item_is_still_refused(engine: Engine) -> None:
    """#34 behaviour: the food foreign key stays RESTRICT; only a user deletion removes items."""
    with engine.begin() as conn:
        user = _user(conn, "a")
        food = _food(conn, user)
        meal = _meal(conn, user, [food])
    with (
        pytest.raises(IntegrityError, match="fk_meal_item_food_id_food"),
        engine.begin() as conn,
    ):
        conn.execute(text("DELETE FROM food WHERE id = :id"), {"id": food})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM meal_item WHERE meal_id = :m", m=meal) == 1
        assert _count(conn, "SELECT count(*) FROM food WHERE id = :f", f=food) == 1


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
            food = _food(conn, user)
            _meal(conn, user, [food])
        down = _alembic(migrated_database_url, "downgrade", "b4d7f1c9e203")
        assert down.returncode == 0, down.stderr
        with engine.connect() as conn:
            triggers = "SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'users_before%'"
            assert _count(conn, triggers) == 0
            assert _count(conn, "SELECT count(*) FROM meal_item") == 1
        up = _alembic(migrated_database_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user})
        with engine.connect() as conn:
            assert _count(conn, "SELECT count(*) FROM meal_item") == 0
    finally:
        engine.dispose()
