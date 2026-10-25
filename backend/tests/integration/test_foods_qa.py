"""QA additions for #34: grams/per-100 g rounding round-trips, mixed visible and hidden foods in
one meal, and the 404 body not echoing the food id."""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Food, Meal, MealItem
from app.seed import run_seed
from tests.integration.auth_helpers import Api, problem

FOODS = "/api/v1/foods"
MEALS = "/api/v1/meals"


@pytest.fixture
def seeded(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    return api


def _food(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "QA food",
        "kcal_per_100g": 200,
        "protein_g_per_100g": 10,
        "carbs_g_per_100g": 20,
        "fat_g_per_100g": 5,
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(("sent", "stored"), [(12.34, 12.3), (12.36, 12.4), (0.05, 0.1)])
def test_meal_item_grams_round_to_a_tenth_and_round_trip(
    seeded: Api, sent: float, stored: float
) -> None:
    food = seeded.client.post(FOODS, json=_food()).json()
    created = seeded.client.post(
        MEALS,
        json={
            "name": "Rounding",
            "slots": ["snack"],
            "items": [{"food_id": food["id"], "grams": sent}],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["items"][0]["grams"] == stored
    listed = seeded.client.get(MEALS, params={"q": "rounding"}).json()["items"]
    assert listed[0]["items"][0]["grams"] == stored
    assert listed[0]["totals"] == created.json()["totals"]
    with Session(seeded.app.state.engine) as session:
        grams = select(MealItem.grams).where(MealItem.meal_id == created.json()["id"])
        assert session.scalars(grams).all() == [stored]


def test_food_per_100g_response_matches_the_stored_row(seeded: Api) -> None:
    created = seeded.client.post(FOODS, json=_food(kcal_per_100g=100.04, protein_g_per_100g=10.06))
    assert created.status_code == 201, created.text
    listed = seeded.client.get(FOODS, params={"source": "custom"}).json()["items"][0]
    with Session(seeded.app.state.engine) as session:
        row = session.scalars(select(Food).where(Food.source == "custom")).one()
    assert (row.kcal_per_100g, row.protein_g_per_100g) == (100.0, 10.1)
    assert created.json()["kcal_per_100g"] == listed["kcal_per_100g"] == row.kcal_per_100g
    assert created.json()["protein_g_per_100g"] == listed["protein_g_per_100g"] == 10.1


def test_meal_mixing_a_seed_food_and_a_hidden_food_is_404_and_creates_nothing(
    seeded: Api,
) -> None:
    hidden = seeded.client.post(FOODS, json=_food(name="Hidden QA food")).json()
    other = seeded.new_client()
    signup = {
        "email": "qa-other@x.test",
        "password": "correct-horse-battery",
        "display_name": "Other",
        "role": "coach",
        "birth_date": "1990-01-01",
        "units": "metric",
        "timezone": "UTC",
        "accept_disclaimer": True,
    }
    assert other.post("/api/v1/auth/signup", json=signup).status_code == 201
    seed_food = other.get(FOODS, params={"q": "banana"}).json()["items"][0]
    with Session(seeded.app.state.engine) as session:
        meals_before = session.scalar(select(func.count()).select_from(Meal))
    response = other.post(
        MEALS,
        json={
            "name": "Mixed",
            "slots": ["snack"],
            "items": [
                {"food_id": seed_food["id"], "grams": 100},
                {"food_id": hidden["id"], "grams": 10},
            ],
        },
    )
    body = problem(response, 404, "food_not_found")
    assert hidden["id"] not in response.text and "Hidden" not in str(body)
    with Session(seeded.app.state.engine) as session:
        assert session.scalar(select(func.count()).select_from(Meal)) == meals_before
