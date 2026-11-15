"""D108 (QA #240 finding 1): a past day always keeps the meal plan that was in force on it, for
any number of "make current" switches, in the day view, the calendar (planned and eaten macros,
nutrition completion) and the adherence chart, also when the plan that applied was deleted."""

from typing import Any

from tests.integration.auth_helpers import Api
from tests.integration.test_plan_activate_delete import _activate, _delete, _new
from tests.integration.test_plan_editor import (
    BASE,
    ME,
    _day,
    _meals_body,
    _plan,
    _put,
    athlete,  # noqa: F401  (fixture)
)

DAYS = ("2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25")  # Thu .. Sun


def _keys(client: Any, day: str) -> set[str]:
    return {
        m["planned_meal"]["meal_key"]
        for m in _day(client, day)["meals"]
        if m["planned_meal"] is not None
    }


def _calendar(client: Any, day: str) -> tuple[Any, ...]:
    body = client.get(f"{ME}/calendar", params={"from": DAYS[0], "to": day}).json()
    d = next(x for x in body["days"] if x["date"] == day)
    return (
        d["planned_meal_count"],
        d["eaten_meal_count"],
        d["nutrition_completion"],
        d["energy"]["planned"],
        d["energy"]["eaten"],
    )


def _adherence(client: Any, day: str) -> Any:
    body = client.get(
        f"{BASE}/athletes/me/charts/adherence", params={"from": DAYS[0], "to": day}
    ).json()
    return next(x for x in body["days"] if x["date"] == day)["nutrition_completion"]


def _snapshot(client: Any, past: tuple[str, ...]) -> dict[str, Any]:
    return {
        day: (_keys(client, day), _calendar(client, day), _adherence(client, day)) for day in past
    }


def _advance(api: Api, **delta: float) -> None:
    api.clock.advance(**delta)
    api.login()  # sessions last 24 h


def _own_meals(client: Any, source: dict[str, Any]) -> None:
    """Give the current plan meals of its own (new keys), copied from `source`."""
    body = _meals_body(source)
    body["revision"] = _plan(client)["revision"]
    for d in body["meal_days"]:
        for m in d["meals"]:
            m["id"] = None
    assert _put(client, "meals", body).status_code == 200


def test_past_days_keep_their_meal_plan_across_repeated_switches_and_a_deleted_plan(
    athlete: Api,  # noqa: F811
) -> None:
    client = athlete.client
    first = _plan(client)
    lunch = _day(client, DAYS[0])["meals"][1]["planned_meal"]
    logged = client.post(
        f"{ME}/meal-logs",
        json={"date": DAYS[0], "planned_meal_id": lunch["id"], "status": "eaten"},
    )
    assert logged.status_code == 201, logged.text
    one = {day: _keys(client, day) for day in DAYS}  # plan 1's meals per day
    assert all(one.values())

    _advance(athlete, hours=16)  # Fri 01:00 UTC: Thursday is past
    _new(client, "Second")
    _own_meals(client, first)  # plan 2, in force on Friday
    two = {day: _keys(client, day) for day in DAYS[1:]}  # plan 2's own meals per day
    assert all(two[d] and two[d].isdisjoint(one[d]) for d in DAYS[1:])
    assert _keys(client, DAYS[0]) == one[DAYS[0]]  # Thursday is past: it stays plan 1's
    _advance(athlete, minutes=30)
    assert _activate(client, 1).status_code == 200  # Fri 01:30: plan 1 again
    assert _keys(client, DAYS[1]) == one[DAYS[1]]

    _advance(athlete, hours=24)  # Sat: Thursday and Friday are past
    past = DAYS[:2]
    before = _snapshot(client, past)
    assert before[DAYS[0]][0] == one[DAYS[0]]
    assert before[DAYS[0]][1][4]["kcal"] > 0  # Thursday's eaten meal is still counted
    assert before[DAYS[0]][1][3]["kcal"] > 0  # and its planned meals
    assert before[DAYS[1]][0] == one[DAYS[1]]  # Friday ended under plan 1

    for number in (2, 1, 2, 1, 2):  # several switches, some within the same day
        _advance(athlete, hours=3)
        assert _activate(client, number).status_code == 200
        assert _snapshot(client, past) == before, f"after making plan {number} current"
    assert _keys(client, DAYS[2]) == two[DAYS[2]]  # today follows the plan made current last

    _advance(athlete, hours=24)  # Sun: Saturday is past too, it ended under plan 2
    saturday = _snapshot(client, DAYS[:3])
    assert saturday[DAYS[2]][0] == two[DAYS[2]]
    assert _activate(client, 1).status_code == 200
    assert _delete(client, 2).status_code == 204  # the plan that applied on Saturday is deleted
    assert _snapshot(client, DAYS[:3]) == saturday  # logged history is unchanged
