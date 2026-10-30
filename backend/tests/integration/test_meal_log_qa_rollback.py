"""QA for #159 (D73, CLAUDE.md rule 8): the meal key migration and the previous release.

A rollback runs the previous image on the new schema (spec §13, `make rollback-compat`). That
release writes planned-meal logs with (slot, slot_index) and no `meal_key`, writes planned meals
without `meal_key`, and matches logs by (slot, slot_index). The xfail tests record what the new
schema and code must tolerate for that to keep working; they flip to XPASS (strict) once fixed.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.integration.auth_helpers import Api
from tests.integration.test_meal_log import ME, THU, _day, _seed_athlete
from tests.integration.test_user_delete_food_cascade import _alembic, _food, _user


def _lunch(api: Api) -> dict[str, object]:
    day = _day(api.client)
    return next(m for m in day["meals"] if m["planned_meal"]["slot"] == "lunch")


@pytest.mark.xfail(
    strict=True,
    raises=IntegrityError,
    reason="#159 QA: ck_meal_log_planned_has_meal_key rejects the previous release's check-off",
)
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


@pytest.mark.xfail(
    strict=True,
    reason="#159 QA: slot_index is no longer written, so the previous release cannot match the log",
)
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


@pytest.mark.xfail(
    strict=True,
    reason="#159 QA: a planned meal without meal_key (written by the previous release) is a 404",
)
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
