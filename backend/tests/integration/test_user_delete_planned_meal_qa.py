"""QA #154 / D66 + D70: the two BEFORE DELETE triggers on `users` (meal items of the user's foods,
planned meals of the user's meals) work together in one user deletion, alongside the D69 SET NULL
author references, and neither weakens the RESTRICT guards on single food / meal deletion (#34)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[Engine]:
    built = create_engine(migrated_database_url)
    yield built
    built.dispose()


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _user(conn: Connection) -> uuid.UUID:
    user_id = _id()
    conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role, birth_date, units,"
            " timezone, disclaimer_accepted_at, created_at, updated_at) VALUES (:id, :email, 'x',"
            " 'T', 'athlete', '1990-01-01', 'metric', 'UTC', now(), now(), now())"
        ),
        {"id": user_id, "email": f"qa-{user_id}@example.com"},
    )
    return user_id


def _food(conn: Connection, owner: uuid.UUID | None) -> uuid.UUID:
    food_id = _id()
    conn.execute(
        text(
            "INSERT INTO food (id, owner_id, source, name, kcal_per_100g, protein_g_per_100g,"
            " carbs_g_per_100g, fat_g_per_100g, diet_tags, allergen_tags) VALUES (:id, :o,"
            " 'custom', :n, 100, 10, 10, 1, '[]', '[]')"
        ),
        {"id": food_id, "o": owner, "n": f"f-{food_id}"},
    )
    return food_id


def _meal(conn: Connection, owner: uuid.UUID | None, foods: list[uuid.UUID]) -> uuid.UUID:
    meal_id = _id()
    conn.execute(
        text(
            "INSERT INTO meal (id, owner_id, source, name, slots) VALUES"
            " (:id, :o, 'custom', :n, '[\"lunch\"]')"
        ),
        {"id": meal_id, "o": owner, "n": f"m-{meal_id}"},
    )
    for position, food_id in enumerate(foods):
        conn.execute(
            text(
                "INSERT INTO meal_item (id, meal_id, food_id, position, grams)"
                " VALUES (:id, :m, :f, :p, 100)"
            ),
            {"id": _id(), "m": meal_id, "f": food_id, "p": position},
        )
    return meal_id


def _plan(
    conn: Connection, athlete: uuid.UUID, created_by: uuid.UUID, meals: list[uuid.UUID]
) -> tuple[uuid.UUID, uuid.UUID]:
    plan_id, day_id = _id(), _id()
    conn.execute(
        text(
            "INSERT INTO plan (id, athlete_id, created_by, version, source, active, revision,"
            " created_at, updated_at) VALUES (:id, :a, :c, 1, 'custom', true, 0, now(), now())"
        ),
        {"id": plan_id, "a": athlete, "c": created_by},
    )
    conn.execute(
        text(
            'INSERT INTO meal_day (id, plan_id, weekday, "order", edited_by)'
            " VALUES (:id, :p, 'mon', 0, :e)"
        ),
        {"id": day_id, "p": plan_id, "e": created_by},
    )
    for position, meal_id in enumerate(meals):
        conn.execute(
            text(
                'INSERT INTO planned_meal (id, meal_day_id, slot, "order", meal_id, portion_factor)'
                " VALUES (:id, :d, 'lunch', :o, :m, 1)"
            ),
            {"id": _id(), "d": day_id, "o": position, "m": meal_id},
        )
    return plan_id, day_id


def _scalar(conn: Connection, sql: str, **params: object) -> object:
    return conn.execute(text(sql), params).scalar_one()


def test_both_user_delete_triggers_and_author_set_null_work_in_one_deletion(
    engine: Engine,
) -> None:
    """A owns food F and meal M (items: F + seed food). B's own meal uses F and B's plan (created
    and edited by A, as a coach would) holds M, B's meal and a seed meal. A also has their own plan
    with M. Deleting A must succeed and leave B with exactly their own rows minus A's content."""
    with engine.begin() as conn:
        a, b = _user(conn), _user(conn)
        seed_food = _food(conn, None)
        a_food = _food(conn, a)
        a_meal = _meal(conn, a, [a_food, seed_food])
        b_meal = _meal(conn, b, [seed_food, a_food])
        seed_meal = _meal(conn, None, [seed_food])
        b_plan, b_day = _plan(conn, b, a, [a_meal, b_meal, seed_meal])
        _plan(conn, a, a, [a_meal])
        conn.execute(
            text(
                "INSERT INTO plan_change (id, plan_id, author_id, change, created_at)"
                " VALUES (:id, :p, :a, '{}', now())"
            ),
            {"id": _id(), "p": b_plan, "a": a},
        )

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})

    with engine.connect() as conn:
        assert _scalar(conn, "SELECT count(*) FROM users WHERE id = :u", u=a) == 0
        assert _scalar(conn, "SELECT count(*) FROM food WHERE owner_id = :u", u=a) == 0
        assert _scalar(conn, "SELECT count(*) FROM meal WHERE owner_id = :u", u=a) == 0
        assert _scalar(conn, "SELECT count(*) FROM plan WHERE athlete_id = :u", u=a) == 0
        # B's plan and day survive; only the planned meal that used A's meal is gone.
        assert _scalar(conn, "SELECT created_by FROM plan WHERE id = :p", p=b_plan) is None
        assert _scalar(conn, "SELECT edited_by FROM meal_day WHERE id = :d", d=b_day) is None
        planned = set(
            conn.execute(
                text("SELECT meal_id FROM planned_meal WHERE meal_day_id = :d"), {"d": b_day}
            ).scalars()
        )
        assert planned == {b_meal, seed_meal}
        # B's meal survives with only the seed-food item (D66).
        items = list(
            conn.execute(
                text("SELECT food_id FROM meal_item WHERE meal_id = :m"), {"m": b_meal}
            ).scalars()
        )
        assert items == [seed_food]
        assert _scalar(conn, "SELECT count(*) FROM plan_change WHERE plan_id = :p", p=b_plan) == 1
        assert (
            _scalar(conn, "SELECT author_id FROM plan_change WHERE plan_id = :p", p=b_plan) is None
        )


def test_deleting_a_used_food_is_still_refused_with_both_triggers_installed(
    engine: Engine,
) -> None:
    with engine.begin() as conn:
        a = _user(conn)
        food = _food(conn, a)
        _meal(conn, a, [food])
    with (
        pytest.raises(IntegrityError, match="fk_meal_item_food_id_food"),
        engine.begin() as conn,
    ):
        conn.execute(text("DELETE FROM food WHERE id = :id"), {"id": food})


def test_a_failed_user_delete_rolls_back_the_trigger_deletes(engine: Engine) -> None:
    """The trigger runs in the deleting transaction: if the delete is rolled back, the linked
    user's planned meals are back too (no partial removal)."""
    with engine.begin() as conn:
        a, b = _user(conn), _user(conn)
        a_meal = _meal(conn, a, [])
        _, b_day = _plan(conn, b, b, [a_meal])
    conn = engine.connect()
    try:
        trans = conn.begin()
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": a})
        assert (
            _scalar(conn, "SELECT count(*) FROM planned_meal WHERE meal_day_id = :d", d=b_day) == 0
        )
        trans.rollback()
    finally:
        conn.close()
    with engine.connect() as check:
        assert _scalar(check, "SELECT count(*) FROM users WHERE id = :u", u=a) == 1
        assert (
            _scalar(check, "SELECT count(*) FROM planned_meal WHERE meal_day_id = :d", d=b_day) == 1
        )
