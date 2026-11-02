"""#54 meal swap suggestions (F7, F8.1, F8.4, D86) against real Postgres: the band, the F7 filters
(slot, diet, allergies, weekly use, same day), order and determinism, past days, unknown keys,
and applying a swap through `PUT /plan/meals` (new `meal_key`, no inherited logs, source custom).
Owner / linked coach / stranger / unlinked coach are covered for this operation by
`test_authorization_matrix.py`; the linked coach is also checked here."""

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.constants import SWAP_KCAL_BAND
from app.models import Food, MealItem
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem, signup_body
from tests.integration.test_coach_links import L, act, person
from tests.integration.test_onboarding import metric_body, onboarding, profile_body

BASE = "/api/v1"
ME = f"{BASE}/athletes/me"
THU = "2026-10-22"  # the test clock is Thursday 2026-10-22 09:00 UTC
LAST_THU = "2026-10-15"
FRI = "2026-10-23"


def _onboarded(api: Api, **profile: Any) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    response = api.client.post(
        f"{ME}/onboarding", json=onboarding(profile_body(**profile), metric_body())
    )
    assert response.status_code == 201, response.text
    return api


@pytest.fixture
def athlete(api: Api) -> Api:
    return _onboarded(api, diet="omnivore", allergies=[], meals_per_day=4)


def _plan(client: TestClient) -> dict[str, Any]:
    response = client.get(f"{ME}/plan")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _swaps(client: TestClient, key: str, athlete: str = "me", **params: str) -> Any:
    return client.get(f"{BASE}/athletes/{athlete}/plan/meals/{key}/swaps", params=params)


def _ok(client: TestClient, key: str, **params: str) -> dict[str, Any]:
    response = _swaps(client, key, **params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_matches_schema(body, "MealSwapList")
    assert body["meal_key"] == key
    return body


def _meals(plan: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [(d, m) for d in plan["meal_days"] for m in d["meals"]]


def _meals_body(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision": plan["revision"],
        "meal_days": [
            {
                "weekday": d["weekday"],
                "meals": [
                    {
                        "id": m["id"],
                        "slot": m["slot"],
                        "meal_id": m["meal"]["id"],
                        "portion_factor": m["portion_factor"],
                    }
                    for m in d["meals"]
                ],
            }
            for d in plan["meal_days"]
        ],
    }


def _tags(api: Api, meal_id: str) -> tuple[set[str], set[str]]:
    with Session(api.app.state.engine) as session:
        foods = session.scalars(
            select(Food)
            .join(MealItem, MealItem.food_id == Food.id)
            .where(MealItem.meal_id == uuid.UUID(meal_id))
        ).all()
    return (
        set.intersection(*(set(f.diet_tags) for f in foods)),
        {a for f in foods for a in f.allergen_tags},
    )


# ───────────── the list ─────────────


def test_alternatives_are_within_ten_percent_of_the_planned_kcal(athlete: Api) -> None:
    plan = _plan(athlete.client)
    seen = 0
    for day, planned in _meals(plan):
        body = _ok(athlete.client, planned["meal_key"])
        kcal = planned["totals"]["kcal"]
        assert len(body["alternatives"]) <= 3 and body["reason"]
        for alt in body["alternatives"]:
            seen += 1
            assert 0.75 <= alt["portion_factor"] <= 1.5
            assert abs(alt["totals"]["kcal"] - kcal) <= SWAP_KCAL_BAND * kcal + 1
            assert alt["name"] and alt["items"]
            assert alt["meal_id"] != planned["meal"]["id"]
            assert alt["meal_id"] not in {m["meal"]["id"] for m in day["meals"]}
    assert seen > 0


def test_the_same_request_twice_gives_the_same_list_closest_first(athlete: Api) -> None:
    plan = _plan(athlete.client)
    key = _meals(plan)[0][1]["meal_key"]
    first, second = _ok(athlete.client, key), _ok(athlete.client, key)
    assert first == second
    kcal = _meals(plan)[0][1]["totals"]["kcal"]
    distance = [abs(a["totals"]["kcal"] - kcal) for a in first["alternatives"]]
    assert distance == sorted(distance) or max(distance) - min(distance) <= 1  # rounding only


def test_the_alternatives_suit_the_slot_of_the_planned_meal(athlete: Api) -> None:
    plan = _plan(athlete.client)
    for _, planned in _meals(plan)[:8]:
        library = {
            m["id"]: m["slots"]
            for m in athlete.client.get(f"{BASE}/meals", params={"limit": 100}).json()["items"]
        }
        for alt in _ok(athlete.client, planned["meal_key"])["alternatives"]:
            assert planned["slot"] in library[alt["meal_id"]]


@pytest.mark.parametrize(
    ("diet", "allergies"),
    [("vegetarian", ["nuts"]), ("vegan", []), ("omnivore", ["gluten", "lactose"])],
)
def test_diet_and_allergies_are_respected(api: Api, diet: str, allergies: list[str]) -> None:
    athlete = _onboarded(api, diet=diet, allergies=allergies)
    total = 0
    for _, planned in _meals(_plan(athlete.client)):
        for alt in _ok(athlete.client, planned["meal_key"])["alternatives"]:
            total += 1
            diets, allergens = _tags(athlete, alt["meal_id"])
            assert diet == "omnivore" or diet in diets
            assert not set(allergies) & allergens
    assert total > 0


def test_a_meal_used_twice_that_week_is_not_offered(athlete: Api) -> None:
    plan = _plan(athlete.client)
    day, target = next(
        (d, m) for d, m in _meals(plan) if _ok(athlete.client, m["meal_key"])["alternatives"]
    )
    alternative = _ok(athlete.client, target["meal_key"])["alternatives"][0]["meal_id"]
    # Put the alternative into the same slot on two other days (kept ids, so keys stay).
    body = _meals_body(plan)
    others = [d for d in body["meal_days"] if d["weekday"] != day["weekday"]]
    for d in others[:2]:
        d["meals"][0] = {**d["meals"][0], "meal_id": alternative, "portion_factor": 1.0}
    response = athlete.client.put(f"{ME}/plan/meals", json=body)
    assert response.status_code == 200, response.text
    after = _plan(athlete.client)
    key = next(m["meal_key"] for _, m in _meals(after) if m["meal_key"] == target["meal_key"])
    assert alternative not in {a["meal_id"] for a in _ok(athlete.client, key)["alternatives"]}


def test_a_meal_already_in_the_day_is_not_offered(athlete: Api) -> None:
    plan = _plan(athlete.client)
    day = plan["meal_days"][0]
    first, second = day["meals"][0], day["meals"][1]
    ids = {m["meal"]["id"] for m in day["meals"]}
    for alt in _ok(athlete.client, first["meal_key"])["alternatives"]:
        assert alt["meal_id"] not in ids
    assert second["meal"]["id"] in ids


# ───────────── errors ─────────────


def test_unknown_key_is_404_and_a_malformed_key_is_rejected(athlete: Api) -> None:
    problem(_swaps(athlete.client, str(uuid.uuid4())), 404, "meal_not_found")
    assert _swaps(athlete.client, "not-a-uuid").status_code in (400, 422)


def test_a_key_of_another_athletes_plan_is_404(api: Api) -> None:
    _onboarded(api)
    key = _meals(_plan(api.client))[0][1]["meal_key"]
    other = api.new_client()
    assert (
        other.post(f"{BASE}/auth/signup", json=signup_body(email="bob@x.test")).status_code == 201
    )
    assert other.post(f"{ME}/onboarding", json=onboarding()).status_code == 201
    problem(_swaps(other, key), 404, "meal_not_found")


def test_past_days_are_422_today_and_future_are_fine(athlete: Api) -> None:
    plan = _plan(athlete.client)
    thursday = next(d for d in plan["meal_days"] if d["weekday"] == "thu")
    key = thursday["meals"][0]["meal_key"]
    problem(_swaps(athlete.client, key, date=LAST_THU), 422, "past_day")
    problem(_swaps(athlete.client, key, date="2020-01-01"), 422, "past_day")
    assert _ok(athlete.client, key, date=THU) == _ok(athlete.client, key)
    assert _ok(athlete.client, key, date="2026-10-29")["meal_key"] == key
    problem(_swaps(athlete.client, key, date=FRI), 422, "wrong_weekday")
    assert _swaps(athlete.client, key, date="22-10-2026").status_code in (400, 422)


def test_today_is_the_users_today_not_utc(api: Api) -> None:
    """02:00 UTC on Friday is still Thursday evening for a user in New York (user's day, rule 5)."""
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert (
        api.client.post(
            f"{BASE}/auth/signup", json=signup_body(timezone="America/New_York")
        ).status_code
        == 201
    )
    assert api.client.post(f"{ME}/onboarding", json=onboarding()).status_code == 201
    api.clock.set(dt.datetime(2026, 10, 23, 2, 0, tzinfo=dt.UTC))
    thursday = next(d for d in _plan(api.client)["meal_days"] if d["weekday"] == "thu")
    key = thursday["meals"][0]["meal_key"]
    assert _swaps(api.client, key, date=THU).status_code == 200  # still Thursday in New York
    problem(_swaps(api.client, key, date=LAST_THU), 422, "past_day")


# ───────────── authorization (the full matrix lives in test_authorization_matrix.py) ─────────────


def test_a_linked_coach_may_read_swaps_and_an_unlinked_coach_may_not(athlete: Api) -> None:
    key = _meals(_plan(athlete.client))[0][1]["meal_key"]
    ana = athlete.client.get(f"{BASE}/me").json()["id"]
    cleo = person(athlete, "cleo@x.test", "coach", "Cleo Coach")
    dan = person(athlete, "dan@x.test", "coach", "Dan Coach")
    link = athlete.client.post(L, json={"coach_id": str(cleo.id)})
    assert link.status_code == 201, link.text
    assert act(cleo, link.json()["id"], "approve").status_code == 200

    response = _swaps(cleo.client, key, ana)
    assert response.status_code == 200, response.text
    assert response.json() == _ok(athlete.client, key)
    problem(_swaps(dan.client, key, ana), 403, "not_linked")
    problem(_swaps(athlete.new_client(), key, ana), 401, "not_authenticated")


# ───────────── applying a swap (existing PUT /plan/meals, D73) ─────────────


def test_applying_a_swap_gives_a_new_key_no_logs_and_a_custom_plan(athlete: Api) -> None:
    plan = _plan(athlete.client)
    thursday = next(d for d in plan["meal_days"] if d["weekday"] == "thu")
    target = next(
        m for m in thursday["meals"] if _ok(athlete.client, m["meal_key"])["alternatives"]
    )
    log = athlete.client.post(
        f"{ME}/meal-logs",
        json={"date": THU, "planned_meal_id": target["id"], "status": "eaten"},
    )
    assert log.status_code == 201, log.text
    swap = _ok(athlete.client, target["meal_key"])["alternatives"][0]

    body = _meals_body(plan)
    day = next(d for d in body["meal_days"] if d["weekday"] == "thu")
    day["meals"] = [
        {
            "slot": target["slot"],  # no id: a new meal, new key, no logs
            "meal_id": swap["meal_id"],
            "portion_factor": swap["portion_factor"],
        }
        if m["id"] == target["id"]
        else m
        for m in day["meals"]
    ]
    saved = athlete.client.put(f"{ME}/plan/meals", json=body)
    assert saved.status_code == 200, saved.text
    after = saved.json()
    assert after["source"] == "custom"
    new_day = next(d for d in after["meal_days"] if d["weekday"] == "thu")
    swapped = next(m for m in new_day["meals"] if m["meal"]["id"] == swap["meal_id"])
    assert swapped["meal_key"] != target["meal_key"]
    assert abs(swapped["totals"]["kcal"] - swap["totals"]["kcal"]) <= 1

    view = athlete.client.get(f"{ME}/days/{THU}").json()
    row = next(m for m in view["meals"] if m["planned_meal"]["id"] == swapped["id"])
    assert row["log"] is None
    assert len(view["extra_meal_logs"]) == 1  # the old log stays visible (D73)
    problem(_swaps(athlete.client, target["meal_key"]), 404, "meal_not_found")
