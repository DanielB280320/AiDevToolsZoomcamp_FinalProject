"""F6 foods and meals against real Postgres: seed, listing, filters, custom rows, visibility,
validation and contract conformance."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Food, Meal, MealItem
from app.models.food import MEAL_SLOTS
from app.seed import run_seed
from app.seed_foods import SEED_FOODS, SEED_MEALS, load_foods, load_meals
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, field_errors, problem

FOODS = "/api/v1/foods"
MEALS = "/api/v1/meals"
NUL = "\x00"
DIETS = ("omnivore", "vegetarian", "vegan", "pescatarian")


def _food(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Secret protein bar",
        "kcal_per_100g": 400,
        "protein_g_per_100g": 30,
        "carbs_g_per_100g": 40,
        "fat_g_per_100g": 10,
        "diet_tags": ["vegetarian", "pescatarian"],
        "allergen_tags": ["nuts"],
    }
    body.update(overrides)
    return body


@pytest.fixture
def seeded(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    return api


def _sign_up(api: Api, email: str, role: str, name: str) -> TestClient:
    client = api.new_client()
    body = {
        "email": email,
        "password": "correct-horse-battery",
        "display_name": name,
        "role": role,
        "birth_date": "1990-01-01",
        "units": "metric",
        "timezone": "Europe/Madrid",
        "accept_disclaimer": True,
    }
    assert client.post("/api/v1/auth/signup", json=body).status_code == 201
    return client


def _all(client: TestClient, url: str, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = {**params, "limit": 100, **({"cursor": cursor} if cursor else {})}
        response = client.get(url, params=query)
        assert response.status_code == 200, response.text
        page = response.json()
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def _food_id(client: TestClient, name: str) -> str:
    return next(f["id"] for f in _all(client, FOODS, q=name) if f["name"] == name)


# ───────────── seed ─────────────


def test_seed_loads_all_foods_and_meals_with_tags(seeded: Api) -> None:
    foods = _all(seeded.client, FOODS)
    meals = _all(seeded.client, MEALS)
    assert len(foods) == len(SEED_FOODS)
    assert len(meals) == len(SEED_MEALS) >= 50
    assert {f["source"] for f in foods} == {"seed"}
    for food in foods:
        assert_matches_schema(food, "Food")
    for meal in meals:
        assert_matches_schema(meal, "Meal")
        assert meal["is_custom"] is False and meal["owner"] is None


def test_coverage_matrix_through_the_api(seeded: Api) -> None:
    for slot in MEAL_SLOTS:
        for diet in DIETS:
            found = _all(seeded.client, MEALS, slot=slot, diet=diet)
            assert found, (slot, diet)
            for meal in found:
                assert slot in meal["slots"]
                assert diet == "omnivore" or diet in meal["diet_tags"]


def _counts(session: Session) -> tuple[int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(Food)) or 0,
        session.scalar(select(func.count()).select_from(Meal)) or 0,
        session.scalar(select(func.count()).select_from(MealItem)) or 0,
    )


def test_seed_is_idempotent_leaves_custom_rows_and_survives_renames(seeded: Api) -> None:
    custom_food = seeded.client.post(FOODS, json=_food()).json()
    ok = seeded.client.post(
        MEALS,
        json={
            "name": "Mine",
            "slots": ["snack"],
            "items": [{"food_id": custom_food["id"], "grams": 50}],
        },
    )
    assert ok.status_code == 201
    engine = seeded.app.state.engine
    with Session(engine) as session:
        before = _counts(session)
        assert run_seed(session) == 0
        assert _counts(session) == before
        # Rename a seed food and a seed meal in place (cf. #103): re-seeding must not crash,
        # duplicate or restore them.
        session.execute(update(Food).where(Food.name == "Banana").values(name="Banana (renamed)"))
        session.execute(
            update(Meal).where(Meal.name == "Tuna on rice cakes").values(name="Tuna cakes")
        )
        session.commit()
        assert load_foods(session) == 0
        assert load_meals(session) == 0
        session.commit()
        assert _counts(session) == before
        assert (
            session.scalar(select(func.count()).select_from(Food).where(Food.name == "Banana")) == 0
        )
    # The custom rows are untouched.
    assert [f["id"] for f in _all(seeded.client, FOODS, source="custom")] == [custom_food["id"]]
    assert [m["name"] for m in _all(seeded.client, MEALS, q="mine")] == ["Mine"]


# ───────────── meals: computed macros ─────────────


def test_custom_meal_macros_are_computed_from_foods_and_grams(seeded: Api) -> None:
    food = seeded.client.post(
        FOODS, json=_food(name="Test food", kcal_per_100g=200, protein_g_per_100g=10)
    ).json()
    created = seeded.client.post(
        MEALS,
        json={
            "name": "Bowl",
            "slots": ["lunch", "dinner"],
            "items": [{"food_id": food["id"], "grams": 150}],
        },
    )
    assert created.status_code == 201, created.text
    meal = created.json()
    assert_matches_schema(meal, "Meal")
    assert meal["totals"] == {"kcal": 300, "protein_g": 15.0, "carbs_g": 60.0, "fat_g": 15.0}
    assert meal["items"][0]["kcal"] == 300 and meal["items"][0]["grams"] == 150
    assert meal["is_custom"] is True and meal["owner"]["role"] == "athlete"
    assert meal["diet_tags"] == ["vegetarian", "pescatarian"]
    assert meal["allergen_tags"] == ["nuts"]
    listed = next(m for m in _all(seeded.client, MEALS, q="bowl") if m["id"] == meal["id"])
    assert listed["totals"] == meal["totals"]


def test_seed_meal_macros_match_the_formula(seeded: Api) -> None:
    foods = {f["name"]: f for f in _all(seeded.client, FOODS)}
    meal = next(m for m in _all(seeded.client, MEALS) if m["name"] == "Apple with peanut butter")
    expected = sum(
        foods[i["food"]["name"]]["kcal_per_100g"] * i["grams"] / 100 for i in meal["items"]
    )
    assert abs(meal["totals"]["kcal"] - expected) <= 0.5


# ───────────── listing and filters ─────────────


def test_food_filters_and_pagination(seeded: Api) -> None:
    vegan = _all(seeded.client, FOODS, diet="vegan")
    assert vegan and all("vegan" in f["diet_tags"] for f in vegan)
    assert not any(f["name"] == "Egg, whole" for f in vegan)
    nut_free = _all(seeded.client, FOODS, exclude_allergens="nuts,gluten")
    assert nut_free and all(not {"nuts", "gluten"} & set(f["allergen_tags"]) for f in nut_free)
    assert [f["name"] for f in _all(seeded.client, FOODS, q="SALMON")] == ["Salmon, cooked"]
    assert len(_all(seeded.client, FOODS, diet="omnivore")) == len(SEED_FOODS)
    page = seeded.client.get(FOODS, params={"limit": 5}).json()
    assert len(page["items"]) == 5 and page["next_cursor"]
    names = [f["name"].lower() for f in _all(seeded.client, FOODS)]
    assert names == sorted(names)


def test_meal_filters_exclude_allergens_and_diets(seeded: Api) -> None:
    free = _all(seeded.client, MEALS, exclude_allergens="nuts,eggs,lactose,fish,shellfish")
    assert free and all(
        not {"nuts", "eggs", "lactose", "fish", "shellfish"} & set(m["allergen_tags"]) for m in free
    )
    vegetarian_breakfast = _all(seeded.client, MEALS, slot="breakfast", diet="vegetarian")
    assert any(m["name"] == "Scrambled eggs on toast" for m in vegetarian_breakfast)
    assert not any(m["name"] == "Salmon and egg breakfast bowl" for m in vegetarian_breakfast)


@pytest.mark.parametrize(
    ("url", "params"),
    [
        (FOODS, {"diet": "keto"}),
        (FOODS, {"exclude_allergens": "gluten,pollen"}),
        (FOODS, {"exclude_allergens": "gluten,gluten"}),
        (FOODS, {"source": "elsewhere"}),
        (FOODS, {"limit": 0}),
        (MEALS, {"slot": "brunch"}),
        (MEALS, {"diet": "paleo"}),
        (MEALS, {"exclude_allergens": "x"}),
        (MEALS, {"cursor": "!!"}),
    ],
)
def test_invalid_query_parameters_are_400(seeded: Api, url: str, params: dict[str, Any]) -> None:
    problem(seeded.client.get(url, params=params), 400, "bad_request")


def test_nul_in_query_is_400(seeded: Api) -> None:
    for url in (FOODS, MEALS):
        body = problem(seeded.client.get(url, params={"q": f"a{NUL}b"}), 400, "bad_request")
        assert ("q", "invalid_format") in field_errors(body)


# ───────────── visibility: owner vs linked coach vs stranger ─────────────


def test_custom_food_and_meal_are_visible_only_to_their_creator(seeded: Api) -> None:
    creator = seeded.client
    athlete = _sign_up(seeded, "bo@x.test", "athlete", "Bo")
    coach = _sign_up(seeded, "coach@x.test", "coach", "Coach")
    food = creator.post(FOODS, json=_food()).json()
    meal = creator.post(
        MEALS,
        json={
            "name": "Secret shake",
            "slots": ["snack"],
            "items": [{"food_id": food["id"], "grams": 40}],
        },
    ).json()

    assert food["id"] in {f["id"] for f in _all(creator, FOODS, q="secret")}
    assert meal["id"] in {m["id"] for m in _all(creator, MEALS, q="secret")}
    for stranger in (athlete, coach):
        assert _all(stranger, FOODS, q="secret") == []
        assert _all(stranger, MEALS, q="secret") == []
        assert food["id"] not in {f["id"] for f in _all(stranger, FOODS)}
        assert meal["id"] not in {m["id"] for m in _all(stranger, MEALS, slot="snack")}
        assert len(_all(stranger, FOODS)) == len(SEED_FOODS)  # seed rows stay visible
        assert len(_all(stranger, MEALS)) == len(SEED_MEALS)


def test_a_coach_can_create_custom_foods_and_meals(seeded: Api) -> None:
    coach = _sign_up(seeded, "coach@x.test", "coach", "Coach")
    created = coach.post(FOODS, json=_food(name="Coach bar"))
    assert created.status_code == 201
    assert created.json()["owner"]["role"] == "coach"
    assert [f["id"] for f in _all(coach, FOODS, source="custom")] == [created.json()["id"]]


def test_a_meal_cannot_use_a_food_the_caller_cannot_see(seeded: Api) -> None:
    other = _sign_up(seeded, "bo@x.test", "athlete", "Bo")
    hidden = seeded.client.post(FOODS, json=_food()).json()
    unknown = "00000000-0000-4000-8000-000000000000"
    for food_id in (hidden["id"], unknown):
        response = other.post(
            MEALS,
            json={"name": "Nope", "slots": ["snack"], "items": [{"food_id": food_id, "grams": 10}]},
        )
        # Same answer for "exists but private" and "does not exist": ids cannot be probed.
        problem(response, 404, "food_not_found")
    assert _all(other, MEALS, q="nope") == []


def test_catalog_requires_authentication(seeded: Api) -> None:
    anonymous = seeded.new_client()
    for method, url in (("get", FOODS), ("post", FOODS), ("get", MEALS), ("post", MEALS)):
        assert getattr(anonymous, method)(url).status_code == 401


# ───────────── validation ─────────────


@pytest.mark.parametrize(
    "overrides",
    [
        {"kcal_per_100g": -1},
        {"protein_g_per_100g": -0.1},
        {"carbs_g_per_100g": 100.1},
        {"fat_g_per_100g": 101},
        {"kcal_per_100g": 901},
        {"kcal_per_100g": "NaN"},
        {"diet_tags": ["keto"]},
        {"diet_tags": ["vegan", "vegan"]},
        {"diet_tags": ["omnivore"]},
        {"allergen_tags": ["pollen"]},
        {"name": "a"},
        {"name": "x" * 121},
        {"brand": "x" * 81},
        {"surprise": 1},
    ],
)
def test_invalid_food_is_422(seeded: Api, overrides: dict[str, Any]) -> None:
    problem(seeded.client.post(FOODS, json=_food(**overrides)), 422, "validation_error")


def test_non_finite_json_numbers_are_rejected(seeded: Api) -> None:
    for literal in ("NaN", "Infinity", "-Infinity"):
        raw = (
            f'{{"name": "Odd food", "kcal_per_100g": {literal}, "protein_g_per_100g": 1, '
            '"carbs_g_per_100g": 1, "fat_g_per_100g": 1}'
        )
        response = seeded.client.post(
            FOODS, content=raw, headers={"content-type": "application/json"}
        )
        assert response.status_code in (400, 422), literal


def test_food_and_meal_names_with_nul_are_422(seeded: Api) -> None:
    body = problem(
        seeded.client.post(FOODS, json=_food(name=f"Bar{NUL}x")), 422, "validation_error"
    )
    assert ("name", "invalid_format") in field_errors(body)
    problem(seeded.client.post(FOODS, json=_food(brand=f"B{NUL}")), 422, "validation_error")
    food = seeded.client.post(FOODS, json=_food()).json()
    item = {"food_id": food["id"], "grams": 10}
    problem(
        seeded.client.post(MEALS, json={"name": f"M{NUL}x", "slots": ["snack"], "items": [item]}),
        422,
        "validation_error",
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["items"][0].update(grams=0),
        lambda b: b["items"][0].update(grams=-5),
        lambda b: b["items"][0].update(grams=2001),
        lambda b: b["items"][0].update(grams="NaN"),
        lambda b: b["items"][0].update(extra=1),
        lambda b: b.update(items=[]),
        lambda b: b.update(items=[b["items"][0]] * 31),
        lambda b: b.update(slots=[]),
        lambda b: b.update(slots=["brunch"]),
        lambda b: b.update(slots=["snack", "snack"]),
        lambda b: b.update(name="x"),
        lambda b: b.update(extra=1),
    ],
)
def test_invalid_meal_is_422(seeded: Api, mutate: Any) -> None:
    food = seeded.client.post(FOODS, json=_food()).json()
    body = {
        "name": "Valid meal",
        "slots": ["snack"],
        "items": [{"food_id": food["id"], "grams": 10}],
    }
    mutate(body)
    problem(seeded.client.post(MEALS, json=body), 422, "validation_error")


def test_stored_values_and_source(seeded: Api) -> None:
    food = seeded.client.post(FOODS, json=_food()).json()
    assert food["source"] == "custom" and food["external_code"] is None
    assert_matches_schema(food, "Food")
    with Session(seeded.app.state.engine) as session:
        row = session.scalars(select(Food).where(Food.source == "custom")).one()
        assert (row.kcal_per_100g, row.protein_g_per_100g) == (400, 30)
        assert row.diet_tags == ["pescatarian", "vegetarian"]
        assert {m.source for m in session.scalars(select(Meal))} == {"seed"}
