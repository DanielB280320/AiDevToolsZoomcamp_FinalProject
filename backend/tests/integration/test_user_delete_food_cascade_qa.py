"""QA edge cases for #131 / D66 (trigger `users_before_delete_remove_meal_items`).

Real Postgres, rows inserted directly (the delete endpoint, links and notifications are other
issues). Covers: many foods across many meals, a food used twice in one meal, a bulk delete of
several users whose foods are used in each other's meals, a deleted user's own meal that contains
another user's food, atomicity when the user delete is rolled back, and the expand-only contract
(trigger present at head, schema of `meal_item` unchanged)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from tests.integration.test_user_delete_food_cascade import _count, _food, _meal, _user


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[Engine]:
    built = create_engine(migrated_database_url)
    yield built
    built.dispose()


def _items(conn: Connection, meal_id: uuid.UUID) -> list[uuid.UUID]:
    rows = conn.execute(
        text("SELECT food_id FROM meal_item WHERE meal_id = :m ORDER BY position"), {"m": meal_id}
    ).scalars()
    return list(rows)


def _no_rows_reference(conn: Connection, user: uuid.UUID, foods: list[uuid.UUID]) -> None:
    assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=user) == 0
    assert _count(conn, "SELECT count(*) FROM food WHERE owner_id = :u", u=user) == 0
    assert _count(conn, "SELECT count(*) FROM meal WHERE owner_id = :u", u=user) == 0
    assert _count(conn, "SELECT count(*) FROM meal_item WHERE food_id = ANY(:f)", f=foods) == 0


def test_user_with_many_foods_used_across_many_own_and_other_meals(engine: Engine) -> None:
    with engine.begin() as conn:
        a = _user(conn, "a")
        b = _user(conn, "b")
        a_foods = [_food(conn, a) for _ in range(15)]
        b_food = _food(conn, b)
        seed = _food(conn, None, source="seed")
        for i in range(25):  # A's own meals, every food used, some twice
            _meal(conn, a, [a_foods[i % 15], a_foods[(i + 1) % 15], a_foods[i % 15], seed])
        b_meals = [
            _meal(conn, b, [a_foods[i % 15], b_food, a_foods[(i + 7) % 15], seed, a_foods[i % 15]])
            for i in range(10)
        ]
        b_only = _meal(conn, b, [a_foods[0], a_foods[1]])  # every item uses A's foods
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
    with engine.connect() as conn:
        _no_rows_reference(conn, a, a_foods)
        for meal in b_meals:
            assert _items(conn, meal) == [b_food, seed]
        # D66: the meal stays even when all its items are removed.
        assert _count(conn, "SELECT count(*) FROM meal WHERE id = :m", m=b_only) == 1
        assert _items(conn, b_only) == []
        assert _count(conn, "SELECT count(*) FROM meal WHERE owner_id = :u", u=b) == 11
        assert _count(conn, "SELECT count(*) FROM food WHERE id = ANY(:f)", f=[b_food, seed]) == 2


def test_food_used_twice_in_the_users_own_meal(engine: Engine) -> None:
    with engine.begin() as conn:
        a = _user(conn, "a")
        food = _food(conn, a)
        _meal(conn, a, [food, food])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
    with engine.connect() as conn:
        _no_rows_reference(conn, a, [food])
        assert _count(conn, "SELECT count(*) FROM meal_item") == 0


def test_bulk_delete_of_users_whose_foods_are_used_in_each_others_meals(engine: Engine) -> None:
    with engine.begin() as conn:
        a, b, c, survivor = (_user(conn, t) for t in ("a", "b", "c", "survivor"))
        fa, fb, fc, fs = _food(conn, a), _food(conn, b), _food(conn, c), _food(conn, survivor)
        _meal(conn, a, [fa, fb])  # cycle: A uses B's, B uses C's, C uses A's
        _meal(conn, b, [fb, fc])
        _meal(conn, c, [fc, fa])
        s_meal = _meal(conn, survivor, [fa, fs, fb, fc, fs])
    with engine.begin() as conn:
        deleted = conn.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [a, b, c]}
        ).rowcount
    assert deleted == 3
    with engine.connect() as conn:
        for user, food in ((a, fa), (b, fb), (c, fc)):
            _no_rows_reference(conn, user, [food])
        assert _items(conn, s_meal) == [fs, fs]
        assert _count(conn, "SELECT count(*) FROM meal") == 1
        assert _count(conn, "SELECT count(*) FROM food") == 1


def test_deleted_users_own_meal_with_another_users_food_keeps_that_food(engine: Engine) -> None:
    """Other cascade path: meal_item rows of A's own meal go through meal_id CASCADE; B's food
    (used in A's meal and in B's meal) must survive, and B's meal must be untouched."""
    with engine.begin() as conn:
        a = _user(conn, "a")
        b = _user(conn, "b")
        fa, fb = _food(conn, a), _food(conn, b)
        _meal(conn, a, [fb, fa, fb])
        b_meal = _meal(conn, b, [fb])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
    with engine.connect() as conn:
        _no_rows_reference(conn, a, [fa])
        assert _count(conn, "SELECT count(*) FROM food WHERE id = :f", f=fb) == 1
        assert _items(conn, b_meal) == [fb]
        assert _count(conn, "SELECT count(*) FROM meal_item") == 1


def test_items_come_back_when_the_user_delete_is_rolled_back(engine: Engine) -> None:
    """The trigger runs inside the deleting transaction, so a failed or aborted account deletion
    must not strip items from other users' meals."""
    with engine.begin() as conn:
        a = _user(conn, "a")
        b = _user(conn, "b")
        fa, fb = _food(conn, a), _food(conn, b)
        b_meal = _meal(conn, b, [fb, fa])
    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
        assert _items(conn, b_meal) == [fb]
        tx.rollback()
    with engine.connect() as conn:
        assert _items(conn, b_meal) == [fb, fa]
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=a) == 1


def test_head_schema_is_expand_only(engine: Engine) -> None:
    """The FK stays RESTRICT (no constraint change for the previous release) and the trigger is
    a per-row BEFORE DELETE trigger on `users` only."""
    with engine.connect() as conn:
        confdeltype = conn.execute(
            text(
                "SELECT confdeltype FROM pg_constraint WHERE conname = 'fk_meal_item_food_id_food'"
            )
        ).scalar_one()
        assert confdeltype == "r"
        rows = conn.execute(
            text(
                "SELECT tgrelid::regclass::text, tgtype FROM pg_trigger"
                " WHERE tgname = 'users_before_delete_remove_meal_items'"
            )
        ).all()
        assert len(rows) == 1
        table, tgtype = rows[0]
        assert table == "users"
        # tgtype bits: 1 = ROW, 2 = BEFORE, 8 = DELETE
        assert tgtype & 1 and tgtype & 2 and tgtype & 8
        assert not tgtype & (4 | 16 | 32)  # not INSERT / UPDATE / TRUNCATE
