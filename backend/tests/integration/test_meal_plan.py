"""#36 F7 meal plan generated with the training plan at onboarding, against real Postgres:
7 meal days within the targets, diet and allergy filters, repeat cap, persistence, warnings,
reads and authorization (owner / stranger / anonymous)."""

import uuid
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Food, Meal, MealDay, MealItem, Plan, PlannedMeal
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem, signup_body
from tests.integration.test_onboarding import ONBOARD, PLAN, metric_body, onboarding, profile_body


@pytest.fixture
def athlete(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    return api


def _onboard(api: Api, **profile: Any) -> dict[str, Any]:
    response = api.client.post(ONBOARD, json=onboarding(profile_body(**profile), metric_body()))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _foods(api: Api, ids: set[str]) -> list[Food]:
    with Session(api.app.state.engine) as session:
        rows = session.scalars(select(Food).where(Food.id.in_([uuid.UUID(i) for i in ids])))
        return list(rows)


def test_onboarding_generates_seven_meal_days_with_the_training_plan(athlete: Api) -> None:
    result = _onboard(athlete, meals_per_day=4)
    plan, targets = result["plan"], result["targets"]
    assert_matches_schema(result, "OnboardingResult")

    days = plan["meal_days"]
    assert [d["weekday"] for d in days] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert plan["training_days"]  # generated together, in the same plan version
    for day in days:
        assert [m["slot"] for m in day["meals"]] == ["breakfast", "lunch", "snack", "dinner"]
        within = abs(day["totals"]["kcal"] - targets["kcal"]) <= 0.05 * targets["kcal"]
        assert within or day["warning"]
        assert day["edited_by"] is None
        assert day["totals"]["kcal"] == sum(m["totals"]["kcal"] for m in day["meals"])
        for meal in day["meals"]:
            assert 0.75 <= meal["portion_factor"] <= 1.5
            assert meal["items"]
    # The follow-up read returns the same plan.
    assert athlete.client.get(PLAN).json() == plan


def test_meal_plan_is_persisted_with_the_plan_version(athlete: Api) -> None:
    result = _onboard(athlete, meals_per_day=3)
    with Session(athlete.app.state.engine) as session:
        plan = session.scalars(select(Plan)).one()
        assert str(plan.id) == result["plan"]["id"]
        days = session.scalars(select(MealDay).where(MealDay.plan_id == plan.id)).all()
        assert len(days) == 7
        planned = session.scalars(select(PlannedMeal)).all()
        assert len(planned) == 21
        assert {p.slot for p in planned} == {"breakfast", "lunch", "dinner"}


def test_f7_2_no_meal_appears_more_than_twice(athlete: Api) -> None:
    result = _onboard(athlete, meals_per_day=5, diet="omnivore", allergies=[])
    uses = Counter(m["meal"]["id"] for d in result["plan"]["meal_days"] for m in d["meals"])
    assert uses and max(uses.values()) <= 2


@pytest.mark.parametrize(
    ("diet", "allergies"),
    [("vegetarian", ["nuts"]), ("vegan", ["soy", "gluten"]), ("pescatarian", ["fish"])],
)
def test_f7_3_diet_and_allergy_filters_hold(athlete: Api, diet: str, allergies: list[str]) -> None:
    result = _onboard(athlete, diet=diet, allergies=allergies, meals_per_day=4)
    ids = {
        i["food"]["id"] for d in result["plan"]["meal_days"] for m in d["meals"] for i in m["items"]
    }
    assert ids
    for food in _foods(athlete, ids):
        assert not set(allergies) & set(food.allergen_tags)
        assert diet in food.diet_tags


def test_scaled_items_follow_the_portion_factor(athlete: Api) -> None:
    result = _onboard(athlete)
    planned = result["plan"]["meal_days"][0]["meals"][0]
    with Session(athlete.app.state.engine) as session:
        base = {
            str(i.food_id): i.grams
            for i in session.scalars(
                select(MealItem).where(MealItem.meal_id == uuid.UUID(planned["meal"]["id"]))
            )
        }
    for item in planned["items"]:
        assert item["grams"] == pytest.approx(
            base[item["food"]["id"]] * planned["portion_factor"], abs=0.06
        )


def test_an_empty_meal_library_still_onboards_with_warnings(athlete: Api) -> None:
    with Session(athlete.app.state.engine) as session:
        session.execute(delete(MealItem))
        session.execute(delete(Meal))
        session.commit()
    result = _onboard(athlete)
    days = result["plan"]["meal_days"]
    assert len(days) == 7
    assert all(d["meals"] == [] and d["warning"] for d in days)
    assert_matches_schema(result, "OnboardingResult")


def test_a_stranger_cannot_read_the_meal_plan(athlete: Api) -> None:
    _onboard(athlete)
    owner_id = athlete.client.get("/api/v1/me").json()["id"]
    stranger = athlete.new_client()
    response = stranger.post(
        "/api/v1/auth/signup", json=signup_body(email="bob@x.test", display_name="Bob")
    )
    assert response.status_code == 201
    problem(stranger.get(f"/api/v1/athletes/{owner_id}/plan"), 403, "not_linked")


def test_an_anonymous_request_is_rejected(athlete: Api) -> None:
    _onboard(athlete)
    assert athlete.new_client().get(PLAN).status_code == 401
