"""QA (PR #240, D108): make current must not rewrite past days; deleted plans must not leak.

Rule 7 / F8.1: past days keep the meal plan that applied then. D108(2) claims an activation
"behaves like a creation at that moment and a day keeps the meal plan that applied then".
"""

from typing import Any

import pytest

from tests.integration.auth_helpers import Api
from tests.integration.test_plan_activate_delete import _activate, _delete, _new
from tests.integration.test_plan_editor import (
    _day,
    _meals_body,
    _plan,
    _put,
    athlete,  # noqa: F401  (fixture)
)

THU = "2026-10-22"  # onboarding day (NOW = Thu 09:00 UTC, Europe/Madrid)
FRI = "2026-10-23"


def _planned_keys(client: Any, day: str) -> set[str]:
    return {
        m["planned_meal"]["meal_key"]
        for m in _day(client, day)["meals"]
        if m["planned_meal"] is not None
    }


def test_make_current_does_not_change_the_meal_plan_of_a_past_day(
    athlete: Api,  # noqa: F811
) -> None:
    client = athlete.client
    first_plan = _plan(client)
    first = _planned_keys(client, THU)
    assert first  # plan 1 (onboarding) has meals on Thursday
    first_fri = _planned_keys(client, FRI)
    assert first_fri

    athlete.clock.advance(hours=16)  # Fri 01:00 UTC = Fri 03:00 Madrid: Thursday is past
    _new(client, "Second")  # plan 2, then give it meals of its own
    meals = _meals_body(first_plan)
    meals["revision"] = _plan(client)["revision"]
    for d in meals["meal_days"]:
        for m in d["meals"]:
            m["id"] = None
    assert _put(client, "meals", meals).status_code == 200
    assert _planned_keys(client, FRI).isdisjoint(first_fri)  # Friday (today) follows plan 2
    assert _planned_keys(client, THU) == first  # a new plan does not rewrite Thursday

    athlete.clock.advance(hours=1)
    assert _activate(client, 1).status_code == 200
    assert _planned_keys(client, FRI) == first_fri  # today follows the newly current plan
    # Thursday was planned and lived under plan 1; making plan 1 current again must not
    # change what Thursday's planned meals were (rule 7).
    assert _planned_keys(client, THU) == first


@pytest.mark.xfail(
    strict=True,
    reason="QA PR #240 note, outside the D108 AC: planned_meals falls back to the newest version "
    "with a meal day for the weekday (pre-existing for an empty new plan) and does not skip "
    "deleted plans, so a deleted plan still supplies today's planned meals",
)
def test_a_deleted_plan_does_not_supply_todays_planned_meals(
    athlete: Api,  # noqa: F811
) -> None:
    client = athlete.client
    athlete.clock.advance(minutes=5)
    _new(client, "Second")  # empty plan: no training days, no meals
    assert _delete(client, 1).status_code == 204
    # Plan 1 is deleted and the current plan has no meals: today shows no planned meal
    # of the deleted plan.
    assert _planned_keys(client, THU) == set()
