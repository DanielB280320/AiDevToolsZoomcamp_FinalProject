"""#158 Accepting a suggestion (a new plan version) keeps the meal plan (F8.1, D70, rule 7)."""

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Meal, MealDay, Plan, PlannedMeal, User
from app.services.plans import create_plan_version
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem
from tests.integration.test_suggestions import _pending_for, _perform, athlete  # noqa: F401
from tests.integration.test_training_log import BASE, THU, _stranger

LATER = "2026-10-29"  # the next Thursday
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SLOTS = ("breakfast", "lunch", "dinner")


def _add_meal_plan(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        plan = session.scalars(select(Plan).where(Plan.active.is_(True))).one()
        meals = list(
            session.scalars(select(Meal).where(Meal.owner_id.is_(None)).order_by(Meal.name))
        )[:3]
        assert len(meals) == 3
        for position, weekday in enumerate(WEEKDAYS):
            plan.meal_days.append(
                MealDay(
                    weekday=weekday,
                    position=position,
                    warning="low protein" if weekday == "thu" else None,
                    meals=[
                        PlannedMeal(slot=s, position=i, meal_id=m.id, portion_factor=1.0 + i / 10)
                        for i, (s, m) in enumerate(zip(SLOTS, meals, strict=True))
                    ],
                )
            )
        session.commit()


def _shape(api: Api, day: str) -> list[Any]:
    response = api.client.get(f"{BASE}/athletes/me/days/{day}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_schema(body, "DayView")
    return [
        (
            m["planned_meal"]["slot"],
            m["planned_meal"]["meal"]["name"],
            [i["grams"] for i in m["planned_meal"]["items"]],
            m["planned_meal"]["totals"],
        )
        for m in body["meals"]
    ]


def test_accepting_a_suggestion_keeps_the_meal_plan(athlete: Api) -> None:  # noqa: F811
    _add_meal_plan(athlete)
    before_past, before_later = _shape(athlete, THU), _shape(athlete, LATER)
    assert len(before_later) == 3 and before_past == before_later
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    response = athlete.client.post(f"{BASE}/suggestions/{suggestion['id']}/accept")
    assert response.status_code == 200, response.text
    plan = athlete.client.get(f"{BASE}/athletes/me/plan").json()
    assert plan["version"] == 2
    assert _shape(athlete, LATER) == before_later
    assert _shape(athlete, THU) == before_past
    with Session(athlete.app.state.engine) as session:
        old, new = (session.scalars(select(Plan).where(Plan.version == v)).one() for v in (1, 2))

        def rows(p: Plan) -> list[Any]:
            return [
                (
                    d.weekday,
                    d.position,
                    d.warning,
                    [(m.slot, m.position, m.meal_id, m.portion_factor) for m in d.meals],
                )
                for d in sorted(p.meal_days, key=lambda d: d.position)
            ]

        assert rows(new) == rows(old) and len(rows(new)) == 7
        assert {m.id for d in new.meal_days for m in d.meals}.isdisjoint(
            {m.id for d in old.meal_days for m in d.meals}
        )  # copies, not shared rows (rule 7)


def test_create_plan_version_can_still_clear_meals_explicitly(athlete: Api) -> None:  # noqa: F811
    _add_meal_plan(athlete)
    with Session(athlete.app.state.engine) as session:
        uid = session.scalars(select(User.id)).one()
        carried = create_plan_version(
            session, athlete_id=uid, author_id=uid, source="custom", days=[],
            now=dt.datetime(2026, 10, 22, tzinfo=dt.UTC),
        )  # fmt: skip
        assert len(carried.meal_days) == 7
        cleared = create_plan_version(
            session, athlete_id=uid, author_id=uid, source="custom", days=[],
            now=dt.datetime(2026, 10, 22, tzinfo=dt.UTC), meal_days=[],
        )  # fmt: skip
        assert cleared.meal_days == []


def test_meal_plan_authorization_is_unchanged(athlete: Api) -> None:  # noqa: F811
    _add_meal_plan(athlete)
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    other = _stranger(athlete)
    coach = _stranger(athlete, "coach@x.test", role="coach")
    with Session(athlete.app.state.engine) as session:
        ana = session.scalars(select(User.id).where(User.email == "ana@x.test")).one()
    for client in (other, coach):
        problem(client.post(f"{BASE}/suggestions/{suggestion['id']}/accept"), 403, "not_linked")
        problem(client.get(f"{BASE}/athletes/{ana}/days/{LATER}"), 403, "not_linked")
    assert athlete.client.post(f"{BASE}/suggestions/{suggestion['id']}/accept").status_code == 200
