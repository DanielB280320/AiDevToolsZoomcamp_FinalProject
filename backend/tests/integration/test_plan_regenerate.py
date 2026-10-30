"""#39 F8.2 regenerate against real Postgres: a new `generated` version from the current profile,
scopes, previous versions kept, meal identity (D73) and authorization."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MealDay, Plan, PlanChange, PlannedMeal
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_plan_editor import (
    BASE,
    ME,
    _meals_body,
    _plan,
    _put,
    _signup,
    _training_body,
    _user_id,
)


@pytest.fixture
def athlete(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    assert api.client.post(ONBOARD, json=onboarding()).status_code == 201
    return api


def _keys(api: Api, version: int) -> list[Any]:
    with Session(api.app.state.engine) as session:
        plan = session.scalars(select(Plan).where(Plan.version == version)).one()
        rows = session.execute(
            select(MealDay.weekday, PlannedMeal.slot, PlannedMeal.position, PlannedMeal.meal_key)
            .join(PlannedMeal, PlannedMeal.meal_day_id == MealDay.id)
            .where(MealDay.plan_id == plan.id)
            .order_by(MealDay.weekday, PlannedMeal.position)
        ).all()
        return [tuple(r) for r in rows]


def _shape(plan: dict[str, Any]) -> Any:
    return (
        [
            (d["weekday"], d["name"], [(e["exercise"]["id"], e["sets"]) for e in d["exercises"]])
            for d in plan["training_days"]
        ],
        [
            (d["weekday"], [(m["slot"], m["meal"]["id"]) for m in d["meals"]])
            for d in plan["meal_days"]
        ],
    )


def test_f8_2_regenerate_after_an_edit_creates_a_generated_version_and_keeps_history(
    athlete: Api,
) -> None:
    first = _plan(athlete.client)
    body = _training_body(first)
    body["training_days"][0]["name"] = "My own"
    body["training_days"][0]["exercises"][0]["sets"] = 6
    edited = _put(athlete.client, "training", body).json()
    assert edited["source"] == "custom"

    response = athlete.client.post(f"{ME}/plan/regenerate")
    assert response.status_code == 201, response.text
    new = response.json()
    assert_matches_schema(new, "Plan")
    assert (new["version"], new["source"], new["active"]) == (3, "generated", True)
    assert new["revision"] == edited["revision"] + 1
    assert new["training_days"][0]["name"] != "My own"
    assert [d["edited_by"] for d in new["training_days"]] == [None] * len(new["training_days"])

    versions = athlete.client.get(f"{ME}/plan/versions").json()["items"]
    assert [(v["version"], v["active"]) for v in versions] == [(3, True), (2, False), (1, False)]
    kept = athlete.client.get(f"{ME}/plan/versions/2").json()
    assert kept["training_days"][0]["name"] == "My own"
    assert kept["training_days"][0]["exercises"][0]["sets"] == 6
    assert athlete.client.get(f"{ME}/plan/versions/1").json()["id"] == first["id"]

    with Session(athlete.app.state.engine) as session:
        plan = session.scalars(select(Plan).where(Plan.version == 3)).one()
        change = session.scalars(select(PlanChange).where(PlanChange.plan_id == plan.id)).one()
        assert change.author_id == _user_id(athlete) and change.author_role == "athlete"
        assert change.change == {"kind": "regenerated", "scope": "all"}


def test_scope_training_copies_the_meals_with_their_keys_and_scope_meals_the_training(
    athlete: Api,
) -> None:
    first = _plan(athlete.client)
    edited = _put(athlete.client, "training", _training_body(first)).json()
    only_training = athlete.client.post(f"{ME}/plan/regenerate", json={"scope": "training"})
    assert only_training.status_code == 201
    assert _shape(only_training.json())[1] == _shape(edited)[1]
    assert _keys(athlete, 3) == _keys(athlete, 2)  # D73: same meal identities

    only_meals = athlete.client.post(f"{ME}/plan/regenerate", json={"scope": "meals"})
    assert only_meals.status_code == 201
    assert _shape(only_meals.json())[0] == _shape(only_training.json())[0]
    assert {k[3] for k in _keys(athlete, 4)}.isdisjoint({k[3] for k in _keys(athlete, 3)})


def test_regenerate_is_deterministic_for_the_same_week_and_profile(athlete: Api) -> None:
    a = athlete.client.post(f"{ME}/plan/regenerate").json()
    b = athlete.client.post(f"{ME}/plan/regenerate").json()
    assert _shape(a) == _shape(b)
    assert b["version"] == a["version"] + 1


def test_regenerate_validates_and_requires_a_plan(athlete: Api) -> None:
    bad = athlete.client.post(f"{ME}/plan/regenerate", json={"scope": "nope"})
    problem(bad, 422, "validation_error")
    problem(athlete.client.post(f"{ME}/plan/regenerate", json={"x": 1}), 422, "validation_error")
    fresh = athlete.new_client()
    assert fresh.post(f"{BASE}/auth/signup", json=_signup("new@x.test")).status_code == 201
    problem(fresh.post(f"{BASE}/athletes/me/plan/regenerate"), 404, "not_onboarded")
    problem(_put(fresh, "training", {"revision": 0, "training_days": []}), 404, "not_onboarded")
    problem(fresh.get(f"{BASE}/athletes/me/plan/versions/1"), 404, "not_found")
    assert fresh.get(f"{BASE}/athletes/me/plan/versions").json() == {"items": []}


def test_meal_edit_after_regenerate_uses_the_new_revision(athlete: Api) -> None:
    athlete.client.post(f"{ME}/plan/regenerate")
    plan = _plan(athlete.client)
    assert plan["revision"] == 1
    stale = _meals_body(plan)
    stale["revision"] = 0
    problem(_put(athlete.client, "meals", stale), 409, "plan_revision_conflict")
    assert _put(athlete.client, "meals", _meals_body(plan)).status_code == 200
