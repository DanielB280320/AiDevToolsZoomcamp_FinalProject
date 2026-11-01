# ruff: noqa: S608  (table names come from schema introspection, never from input)
"""QA additions for #50 (F18): logged meals in the content_removed rule (owner decision
2026-10-31, D85), no side effect of a wrong password over every table, F18.2 for a coach
deletion, and one `link_ended` per athlete of a deleted coach."""

import datetime as dt
import uuid

from sqlalchemy import Engine, inspect, text

from tests.integration.test_account_export_delete import (
    API,
    World,
    _delete,
    _link,
    _person,
    _reachable,
    _removed,
    world,  # noqa: F401  (fixture)
)
from tests.integration.test_user_delete_food_cascade import _food


def _log_food(conn: object, athlete: uuid.UUID, food: uuid.UUID) -> uuid.UUID:
    log_id = uuid.uuid4()
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO meal_log (id, athlete_id, date, status, logged_at)"
            " VALUES (:id, :a, '2026-10-21', 'extra', :t)"
        ),
        {"id": log_id, "a": athlete, "t": dt.datetime(2026, 10, 21, 12, tzinfo=dt.UTC)},
    )
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO meal_log_item (id, meal_log_id, food_id, position, grams)"
            " VALUES (:id, :l, :f, 0, 100)"
        ),
        {"id": uuid.uuid4(), "l": log_id, "f": food},
    )
    return log_id


def test_qa_logged_meal_losing_a_custom_food_notifies_once(world: World) -> None:  # noqa: F811
    """Owner decision 2026-10-31 on #50 / D85: logged meals count, once per affected user."""
    with world.engine.begin() as conn:
        f1, f2 = _food(conn, world.cleo.id), _food(conn, world.cleo.id)
        _log_food(conn, world.ana.id, f1)
        _log_food(conn, world.ana.id, f2)
    assert _delete(world.cleo).status_code == 204
    removed = _removed(world.ana)
    assert len(removed) == 1, removed
    assert removed[0]["payload"] == {}


def _counts(engine: Engine) -> dict[str, int]:
    insp = inspect(engine)
    with engine.connect() as conn:
        return {
            t: int(conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one())
            for t in insp.get_table_names()
        }


def test_qa_wrong_password_changes_no_table(world: World) -> None:  # noqa: F811
    with world.engine.begin() as conn:
        _log_food(conn, world.bob.id, _food(conn, world.ana.id))
    before = _counts(world.engine)
    r = _delete(world.ana, "not-the-password")
    assert r.status_code == 403
    assert "set-cookie" not in {k.lower() for k in r.headers}
    assert _counts(world.engine) == before
    assert world.ana.client.get(f"{API}/me").status_code == 200


def test_qa_coach_deletion_leaves_no_row_referencing_the_coach(world: World) -> None:  # noqa: F811
    r = world.cleo.client.post(
        f"{API}/athletes/{world.ana.id}/notes",
        json={"scope": "day", "date": "2026-10-22", "text": "x"},
    )
    assert r.status_code == 201, r.text
    before = _reachable(world.engine, world.cleo.id)
    assert {"coach_link", "coach_note"} <= set(before), before
    assert _delete(world.cleo).status_code == 204
    insp = inspect(world.engine)
    with world.engine.connect() as conn:
        for table, ids in before.items():
            if any(c["name"] == "id" for c in insp.get_columns(table)):
                n = conn.execute(
                    text(f'SELECT count(*) FROM "{table}" WHERE id = ANY(:ids)'),
                    {"ids": list(ids)},
                ).scalar_one()
                assert n == 0, table
        for table in insp.get_table_names():
            for fk in insp.get_foreign_keys(table):
                if fk["referred_table"] == "users":
                    col = fk["constrained_columns"][0]
                    n = conn.execute(
                        text(f'SELECT count(*) FROM "{table}" WHERE "{col}" = :u'),
                        {"u": world.cleo.id},
                    ).scalar_one()
                    assert n == 0, f"{table}.{col}"
        # No JSON payload left that names the deleted coach.
        n = conn.execute(
            text("SELECT count(*) FROM notification WHERE payload::text LIKE :u"),
            {"u": f"%{world.cleo.id}%"},
        ).scalar_one()
        assert n == 0


def test_qa_each_athlete_of_a_deleted_coach_gets_one_empty_link_ended(
    world: World,  # noqa: F811
) -> None:
    dan = _person(world.api, "dan@x.test")
    _link(dan, world.cleo)
    assert _delete(world.cleo).status_code == 204
    for p in (world.ana, dan):
        items = p.client.get(f"{API}/notifications").json()["items"]
        ended = [i for i in items if i["type"] == "link_ended"]
        assert len(ended) == 1 and ended[0]["payload"] == {}, items
    items = world.bob.client.get(f"{API}/notifications").json()["items"]
    assert not [i for i in items if i["type"] == "link_ended"]
