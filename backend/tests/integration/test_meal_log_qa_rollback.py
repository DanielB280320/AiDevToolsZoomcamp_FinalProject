"""QA for #159 (D73, CLAUDE.md rule 8): the meal key migration and the previous release.

A rollback runs the previous image on the new schema (spec §13, `make rollback-compat`). That
release writes planned-meal logs with (slot, slot_index) and no `meal_key`, writes planned meals
without `meal_key`, and matches logs by (slot, slot_index). These tests guard that the new
schema and code tolerate that (triggers fill the key, slot_index is still written).
"""

import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.integration.auth_helpers import Api
from tests.integration.test_meal_log import ME, THU, _day, _seed_athlete
from tests.integration.test_user_delete_food_cascade import _alembic, _food, _user


def _lunch(api: Api) -> dict[str, object]:
    day = _day(api.client)
    return next(m for m in day["meals"] if m["planned_meal"]["slot"] == "lunch")


def test_previous_release_planned_checkoff_insert_is_accepted_on_the_new_schema(
    api: Api,
) -> None:
    _seed_athlete(api)
    lunch = _lunch(api)
    planned = lunch["planned_meal"]
    assert isinstance(planned, dict)
    with Session(api.app.state.engine) as session:
        athlete = session.execute(text("SELECT id FROM users")).scalar_one()
        # The exact column set main's `log_meal` inserts for a planned meal.
        session.execute(
            text(
                "INSERT INTO meal_log (id, athlete_id, date, planned_meal_id, status, slot,"
                " slot_index, logged_at) VALUES (:id, :a, :d, :p, 'eaten', 'lunch', 0, now())"
            ),
            {"id": uuid.uuid4(), "a": athlete, "d": THU, "p": planned["id"]},
        )
        session.commit()


def test_a_new_log_still_records_its_slot_index_for_the_previous_release(api: Api) -> None:
    _seed_athlete(api)
    planned = _lunch(api)["planned_meal"]
    assert isinstance(planned, dict)
    posted = api.client.post(
        f"{ME}/meal-logs", json={"date": THU, "planned_meal_id": planned["id"], "status": "eaten"}
    )
    assert posted.status_code == 201, posted.text
    with Session(api.app.state.engine) as session:
        slot_index = session.execute(
            text("SELECT slot_index FROM meal_log WHERE id = :i"),
            {"i": posted.json()["meal_log"]["id"]},
        ).scalar_one()
    assert slot_index == 0


def test_a_planned_meal_written_without_a_key_can_still_be_checked_off(api: Api) -> None:
    _seed_athlete(api)
    planned = _lunch(api)["planned_meal"]
    assert isinstance(planned, dict)
    with Session(api.app.state.engine) as session:
        # What a planned_meal row inserted by the previous release looks like.
        session.execute(
            text("UPDATE planned_meal SET meal_key = NULL WHERE id = :i"), {"i": planned["id"]}
        )
        session.commit()
    posted = api.client.post(
        f"{ME}/meal-logs", json={"date": THU, "planned_meal_id": planned["id"], "status": "eaten"}
    )
    assert posted.status_code == 201, posted.text


def test_migration_downgrade_succeeds_with_logs_written_by_the_new_release(
    migrated_database_url: str,
) -> None:
    """Two planned logs in one slot written by the new code (slot_index NULL) must not block the
    re-creation of the old (athlete, date, slot, slot_index) unique index."""
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "a")
            food = _food(conn, athlete)
            for _ in range(2):
                log_id = uuid.uuid4()
                conn.execute(
                    text(
                        "INSERT INTO meal_log (id, athlete_id, date, planned_meal_id, status,"
                        " slot, meal_key, logged_at) VALUES (:id, :a, '2026-10-22', :p, 'eaten',"
                        " 'snack', :k, now())"
                    ),
                    {"id": log_id, "a": athlete, "p": uuid.uuid4(), "k": uuid.uuid4()},
                )
                conn.execute(
                    text(
                        "INSERT INTO meal_log_item (id, meal_log_id, food_id, position, grams)"
                        " VALUES (:id, :l, :f, 0, 100)"
                    ),
                    {"id": uuid.uuid4(), "l": log_id, "f": food},
                )
        down = _alembic(migrated_database_url, "downgrade", "a7d2e5c9b148")
        assert down.returncode == 0, down.stderr
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM meal_log")).scalar_one() == 2
        up = _alembic(migrated_database_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        with engine.connect() as conn:
            keys = conn.execute(text("SELECT count(meal_key) FROM meal_log")).scalar_one()
            assert keys == 2  # the upgrade re-keys the rows the downgrade stripped
    finally:
        engine.dispose()


def test_a_log_and_meals_written_by_the_previous_release_match_after_roll_forward(
    api: Api,
) -> None:
    _seed_athlete(api)
    lunch = _lunch(api)["planned_meal"]
    assert isinstance(lunch, dict)
    with Session(api.app.state.engine) as session:
        athlete = session.execute(text("SELECT id FROM users")).scalar_one()
        # Meals as the previous release writes them (no key; the trigger fills it), then its
        # check-off with (slot, slot_index) and no key.
        session.execute(text("UPDATE planned_meal SET meal_key = NULL"))
        session.execute(
            text(
                "INSERT INTO meal_log (id, athlete_id, date, planned_meal_id, status, slot,"
                " slot_index, logged_at) VALUES (:id, :a, :d, :p, 'eaten', 'lunch', 0, now())"
            ),
            {"id": uuid.uuid4(), "a": athlete, "d": THU, "p": lunch["id"]},
        )
        session.commit()
        assert (
            session.execute(
                text("SELECT count(*) FROM planned_meal WHERE meal_key IS NULL")
            ).scalar_one()
            == 0
        )
    day = _day(api.client)
    matched = next(m for m in day["meals"] if m["planned_meal"]["slot"] == "lunch")
    assert matched["log"] is not None and matched["log"]["status"] == "eaten"
    assert day["extra_meal_logs"] == []
    again = api.client.post(
        f"{ME}/meal-logs", json={"date": THU, "planned_meal_id": lunch["id"], "status": "eaten"}
    )
    assert again.status_code == 200


def test_an_old_release_checkoff_of_a_meal_made_by_the_new_release_matches(api: Api) -> None:
    """The meal keeps its uuid key (new release); the old release's log has no key and takes
    the meal's key from the trigger, so after roll-forward it shows checked and a re-check is a
    repeat, not a duplicate."""
    _seed_athlete(api)
    meals = _day(api.client)["meals"]
    lunch = next(m for m in meals if m["planned_meal"]["slot"] == "lunch")["planned_meal"]
    with Session(api.app.state.engine) as session:
        athlete = session.execute(text("SELECT id FROM users")).scalar_one()
        key = session.execute(
            text("SELECT meal_key FROM planned_meal WHERE id = :i"), {"i": lunch["id"]}
        ).scalar_one()
        # An index that the position formula would not map to this meal's key.
        session.execute(
            text(
                "INSERT INTO meal_log (id, athlete_id, date, planned_meal_id, status, slot,"
                " slot_index, logged_at) VALUES (:id, :a, :d, :p, 'eaten', 'lunch', 0, now())"
            ),
            {"id": uuid.uuid4(), "a": athlete, "d": THU, "p": lunch["id"]},
        )
        session.commit()
        stored = session.execute(text("SELECT meal_key FROM meal_log")).scalar_one()
        assert stored == key
    day = _day(api.client)
    matched = next(m for m in day["meals"] if m["planned_meal"]["slot"] == "lunch")
    assert matched["log"] is not None and day["extra_meal_logs"] == []
    kcal = day["energy"]["eaten"]["kcal"]
    again = api.client.post(
        f"{ME}/meal-logs", json={"date": THU, "planned_meal_id": lunch["id"], "status": "eaten"}
    )
    assert again.status_code == 200
    with Session(api.app.state.engine) as session:
        assert session.execute(text("SELECT count(*) FROM meal_log")).scalar_one() == 1
    assert again.json()["energy"]["eaten"]["kcal"] == kcal
