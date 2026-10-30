"""QA round 2 for #37 (F12, D70): the (date, slot, slot index) identity of a planned meal.

A past day keeps the plan version it was planned with (its ids, its log); a later version only
affects days from its creation day on. Within a day whose plan changes, a log follows its slot
position (D70): reordering or removing meals of one slot moves or detaches the log, but
`energy.eaten` (the grams snapshot) never changes and every counted log stays visible."""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Exercise, Meal, User
from app.seed import run_seed
from app.services.plans import (
    NewMealDay,
    NewPlannedExercise,
    NewPlannedMeal,
    NewTrainingDay,
    create_plan_version,
)
from tests.integration.auth_helpers import NOW, Api
from tests.integration.test_meal_log import ME, THU, WEEKDAYS, _day, _seed_athlete

WED = "2026-10-21"  # the day before NOW (Thursday)


def _version(api: Api, slots: list[tuple[str, int]], now: dt.datetime) -> list[uuid.UUID]:
    """A plan version whose every weekday has `slots` = [(slot, meal number)]."""
    with Session(api.app.state.engine) as session:
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
                NewMealDay(w, [NewPlannedMeal(s, meals[n], 1.0) for s, n in slots])
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


def test_reordering_a_slots_meals_today_moves_the_log_but_never_changes_eaten(api: Api) -> None:
    """The edge case flagged by the engineer, documented as the D70 behaviour."""
    _signup_with_two_snacks(api)
    _, b = _snacks(_day(api.client))
    logged = _post(api, THU, planned_meal_id=b["planned_meal"]["id"], status="eaten")
    assert logged.status_code == 201
    before = _day(api.client)
    assert before["nutrition_completion"] == 0.5

    # Same day: the two snacks swap places.
    _version(api, [("snack", 1), ("snack", 0)], NOW)
    after = _day(api.client)
    first, second = _snacks(after)
    assert first["planned_meal"]["meal"]["id"] == b["planned_meal"]["meal"]["id"]
    assert first["log"] is None
    assert second["log"]["id"] == logged.json()["meal_log"]["id"]  # follows position 1
    assert after["energy"]["eaten"] == before["energy"]["eaten"]  # grams snapshot
    assert after["nutrition_completion"] == 0.5


def test_removing_a_slots_meal_today_keeps_its_log_visible_and_undoable(api: Api) -> None:
    _signup_with_two_snacks(api)
    _, b = _snacks(_day(api.client))
    logged = _post(api, THU, planned_meal_id=b["planned_meal"]["id"], status="eaten").json()
    before = _day(api.client)

    _version(api, [("snack", 0)], NOW)
    after = _day(api.client)
    assert [m["log"] for m in _snacks(after)] == [None]
    extra = {log["id"]: log for log in after["extra_meal_logs"]}
    assert extra[logged["meal_log"]["id"]]["status"] == "eaten"
    assert after["energy"]["eaten"] == before["energy"]["eaten"]
    deleted = api.client.delete(f"{ME}/meal-logs/{logged['meal_log']['id']}")
    assert deleted.status_code in (200, 204), deleted.text
    assert _day(api.client)["extra_meal_logs"] == []
