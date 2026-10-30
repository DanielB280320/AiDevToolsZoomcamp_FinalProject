"""QA round 2 for #37 and #159 (F12, D70, D73): the meal key identity of a planned meal.

A past day keeps the plan version it was planned with (its ids, its log); a later version only
affects days from its creation day on. Within a day whose plan changes, a log belongs to the
meal it was made for (`planned_meal.meal_key`, copied forward by plan versions), not to a
position: a reorder keeps every log on its meal, removing a meal moves its log to
`extra_meal_logs`, and `energy.eaten` never counts a meal twice."""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Exercise, Meal, MealDay, MealLog, Plan, User
from app.seed import run_seed
from app.services.plans import (
    NewMealDay,
    NewPlannedExercise,
    NewPlannedMeal,
    NewTrainingDay,
    create_plan_version,
)
from tests.conftest import Captured
from tests.integration.auth_helpers import NOW, Api
from tests.integration.test_meal_log import ME, THU, WEEKDAYS, _day, _seed_athlete
from tests.integration.test_meal_log_qa import _checkoffs
from tests.integration.test_meal_log_qa import captured as _captured_fixture

captured = _captured_fixture
WED = "2026-10-21"  # the day before NOW (Thursday)


def _version(
    api: Api,
    slots: list[tuple[str, int]],
    now: dt.datetime,
    keep: list[int | None] | None = None,
) -> list[uuid.UUID]:
    """A plan version whose every weekday has `slots` = [(slot, meal number)].

    `keep[i]` is the position, in the active version's day, of the meal that `slots[i]` carries
    forward (its meal key, as a plan edit does); None or no `keep` makes a new meal."""
    with Session(api.app.state.engine) as session:
        old_keys: dict[str, list[uuid.UUID | None]] = {
            d.weekday: [m.meal_key for m in d.meals]
            for d in session.scalars(
                select(MealDay).join(Plan, Plan.id == MealDay.plan_id).where(Plan.active.is_(True))
            )
        }
        uid = session.scalars(select(User.id)).one()
        exercise = session.scalars(select(Exercise).where(Exercise.owner_id.is_(None))).first()
        meals = [
            m.id
            for m in session.scalars(
                select(Meal).where(Meal.owner_id.is_(None)).order_by(Meal.name)
            )
        ][:4]
        assert exercise is not None and len(meals) == 4
        create_plan_version(
            session,
            athlete_id=uid,
            author_id=uid,
            source="custom",
            days=[
                NewTrainingDay(
                    "mon",
                    "Day",
                    [NewPlannedExercise(exercise.id, 3, 90, "linear", 2.5, reps_min=8, reps_max=8)],
                )
            ],
            meal_days=[
                NewMealDay(
                    w,
                    [
                        NewPlannedMeal(
                            s,
                            meals[n],
                            1.0,
                            old_keys[w][k] if keep and (k := keep[i]) is not None else None,
                        )
                        for i, (s, n) in enumerate(slots)
                    ],
                )
                for w in WEEKDAYS
            ],
            now=now,
        )
        session.commit()
        return meals


def _signup_with_two_snacks(api: Api) -> None:
    assert api.signup(email="ana@x.test").status_code == 201
    with Session(api.app.state.engine) as session:
        run_seed(session)
    _version(api, [("snack", 0), ("snack", 1)], NOW - dt.timedelta(days=60))


def _post(api: Api, day: str, **body: Any) -> Any:
    return api.client.post(f"{ME}/meal-logs", json={"date": day, **body})


def _snacks(day: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in day["meals"] if m["planned_meal"]["slot"] == "snack"]


def test_a_past_day_keeps_its_version_and_rejects_the_new_versions_ids(api: Api) -> None:
    _seed_athlete(api)
    wed = _day(api.client, WED)
    old_lunch = next(m for m in wed["meals"] if m["planned_meal"]["slot"] == "lunch")
    first = _post(api, WED, planned_meal_id=old_lunch["planned_meal"]["id"], status="eaten")
    assert first.status_code == 201
    logged_wed = _day(api.client, WED)

    # Today a different meal plan starts (other meals in every slot).
    _version(api, [("breakfast", 3), ("lunch", 2), ("dinner", 1)], NOW)

    wed_after = _day(api.client, WED)
    assert [m["planned_meal"]["id"] for m in wed_after["meals"]] == [
        m["planned_meal"]["id"] for m in wed["meals"]
    ], "a later version rewrote a past day's planned meals"
    assert wed_after["energy"]["eaten"] == logged_wed["energy"]["eaten"]
    assert wed_after["nutrition_completion"] == logged_wed["nutrition_completion"]
    lunch = next(m for m in wed_after["meals"] if m["planned_meal"]["slot"] == "lunch")
    assert lunch["log"]["id"] == first.json()["meal_log"]["id"]

    thu = _day(api.client, THU)
    assert {m["planned_meal"]["id"] for m in thu["meals"]}.isdisjoint(
        {m["planned_meal"]["id"] for m in wed["meals"]}
    )
    # Today's ids do not exist on Wednesday; Wednesday's repeat stays idempotent.
    new_lunch = next(m for m in thu["meals"] if m["planned_meal"]["slot"] == "lunch")
    wrong = _post(api, WED, planned_meal_id=new_lunch["planned_meal"]["id"], status="eaten")
    assert wrong.status_code == 404 and wrong.json()["code"] == "planned_meal_not_found"
    again = _post(api, WED, planned_meal_id=old_lunch["planned_meal"]["id"], status="eaten")
    assert again.status_code == 200
    assert again.json()["meal_log"]["id"] == first.json()["meal_log"]["id"]


def _snack_rows(api: Api) -> int:
    with Session(api.app.state.engine) as session:
        return int(session.scalar(select(func.count()).select_from(MealLog)) or 0)


def test_reordering_a_slots_meals_today_keeps_the_log_on_its_meal(api: Api) -> None:
    _signup_with_two_snacks(api)
    a, b = _snacks(_day(api.client))
    logged = _post(api, THU, planned_meal_id=b["planned_meal"]["id"], status="eaten")
    assert logged.status_code == 201
    before = _day(api.client)
    assert before["nutrition_completion"] == 0.5

    # Same day: the two snacks swap places.
    _version(api, [("snack", 1), ("snack", 0)], NOW, keep=[1, 0])
    after = _day(api.client)
    first, second = _snacks(after)
    assert first["planned_meal"]["meal"]["id"] == b["planned_meal"]["meal"]["id"]
    assert first["log"]["id"] == logged.json()["meal_log"]["id"]
    assert first["log"]["status"] == "eaten"
    assert first["log"]["totals"] == logged.json()["meal_log"]["totals"]
    assert first["log"]["planned_meal_id"] == first["planned_meal"]["id"]
    assert second["planned_meal"]["meal"]["id"] == a["planned_meal"]["meal"]["id"]
    assert second["log"] is None
    assert after["extra_meal_logs"] == []
    assert after["energy"]["eaten"]["kcal"] == first["planned_meal"]["totals"]["kcal"]
    assert after["energy"]["eaten"] == before["energy"]["eaten"]
    assert after["nutrition_completion"] == 0.5


def test_checking_a_reordered_meal_off_again_returns_the_log_and_does_not_count(
    captured: tuple[Api, Captured],
) -> None:
    api, cap = captured
    _version(api, [("snack", 0), ("snack", 1)], NOW - dt.timedelta(days=60))
    _, b = _snacks(_day(api.client))
    logged = _post(api, THU, planned_meal_id=b["planned_meal"]["id"], status="eaten")
    assert logged.status_code == 201
    _version(api, [("snack", 1), ("snack", 0)], NOW, keep=[1, 0])
    before = _day(api.client)
    new_b = _snacks(before)[0]["planned_meal"]["id"]
    counted = _checkoffs(cap)

    again = _post(api, THU, planned_meal_id=new_b, status="eaten")
    assert again.status_code == 200, again.text
    assert again.json()["meal_log"]["id"] == logged.json()["meal_log"]["id"]
    assert again.json()["energy"]["eaten"] == before["energy"]["eaten"]
    assert _snack_rows(api) == 1
    assert _checkoffs(cap) == counted


def test_the_same_meal_twice_in_a_slot_keeps_two_independent_logs_after_a_reorder(
    api: Api,
) -> None:
    assert api.signup(email="ana@x.test").status_code == 201
    with Session(api.app.state.engine) as session:
        run_seed(session)
    _version(api, [("snack", 0), ("snack", 0)], NOW - dt.timedelta(days=60))
    first, second = _snacks(_day(api.client))
    assert (
        _post(api, THU, planned_meal_id=first["planned_meal"]["id"], status="eaten").status_code
        == 201
    )
    assert (
        _post(api, THU, planned_meal_id=second["planned_meal"]["id"], status="skipped").status_code
        == 201
    )

    _version(api, [("snack", 0), ("snack", 0)], NOW, keep=[1, 0])
    after = _snacks(_day(api.client))
    assert [m["log"]["status"] for m in after] == ["skipped", "eaten"]
    assert _snack_rows(api) == 2
    # Each log is still addressable by the current ids and stays independent.
    again = _post(api, THU, planned_meal_id=after[0]["planned_meal"]["id"], status="skipped")
    assert again.status_code == 200
    final = _snacks(_day(api.client))
    assert [m["log"]["status"] for m in final] == ["skipped", "eaten"]
    assert _snack_rows(api) == 2


def test_removing_a_slots_meal_today_keeps_its_log_visible_and_undoable(api: Api) -> None:
    _signup_with_two_snacks(api)
    _, b = _snacks(_day(api.client))
    logged = _post(api, THU, planned_meal_id=b["planned_meal"]["id"], status="eaten").json()
    before = _day(api.client)

    _version(api, [("snack", 0)], NOW, keep=[0])
    after = _day(api.client)
    assert [m["log"] for m in _snacks(after)] == [None]
    extra = {log["id"]: log for log in after["extra_meal_logs"]}
    assert extra[logged["meal_log"]["id"]]["status"] == "eaten"
    assert after["energy"]["eaten"] == before["energy"]["eaten"]
    deleted = api.client.delete(f"{ME}/meal-logs/{logged['meal_log']['id']}")
    assert deleted.status_code in (200, 204), deleted.text
    assert _day(api.client)["extra_meal_logs"] == []


def test_a_meal_added_before_a_logged_one_does_not_take_over_its_log(api: Api) -> None:
    _signup_with_two_snacks(api)
    _, b = _snacks(_day(api.client))
    logged = _post(api, THU, planned_meal_id=b["planned_meal"]["id"], status="eaten").json()
    _version(api, [("snack", 2), ("snack", 0), ("snack", 1)], NOW, keep=[None, 0, 1])
    new, _, moved = _snacks(_day(api.client))
    assert new["log"] is None
    assert moved["log"]["id"] == logged["meal_log"]["id"]


def test_migration_backfills_meal_keys_so_existing_logs_keep_their_meal(
    migrated_database_url: str,
) -> None:
    from sqlalchemy import create_engine

    from tests.integration.test_user_delete_food_cascade import _alembic, _food, _user
    from tests.integration.test_user_delete_planned_meal import _meal, _plan

    engine = create_engine(migrated_database_url)
    try:
        down = _alembic(migrated_database_url, "downgrade", "a7d2e5c9b148")
        assert down.returncode == 0, down.stderr
        with engine.begin() as conn:
            athlete = _user(conn, "a")
            food = _food(conn, athlete)
            day = _plan(conn, athlete, [_meal(conn, athlete), _meal(conn, athlete)])
            second = conn.execute(
                text('SELECT id FROM planned_meal WHERE meal_day_id = :d AND "order" = 1'),
                {"d": day},
            ).scalar_one()
            log_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO meal_log (id, athlete_id, date, planned_meal_id, status, slot,"
                    " slot_index, logged_at) VALUES (:id, :a, '2026-10-26', :p, 'eaten', 'lunch',"
                    " 1, now())"
                ),
                {"id": log_id, "a": athlete, "p": second},
            )
            conn.execute(
                text(
                    "INSERT INTO meal_log_item (id, meal_log_id, food_id, position, grams)"
                    " VALUES (:id, :l, :f, 0, 100)"
                ),
                {"id": uuid.uuid4(), "l": log_id, "f": food},
            )
        up = _alembic(migrated_database_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        with engine.connect() as conn:
            log_key = conn.execute(
                text("SELECT meal_key FROM meal_log WHERE id = :i"), {"i": log_id}
            ).scalar_one()
            meal_key = conn.execute(
                text("SELECT meal_key FROM planned_meal WHERE id = :i"), {"i": second}
            ).scalar_one()
            assert log_key is not None and log_key == meal_key
    finally:
        engine.dispose()
