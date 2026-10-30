"""QA for #36 (PR #145): migration b4d7f1c9e203 round trip with data, the athlete's own vs. a
stranger's custom meals in the generated plan, warnings on the meal day vs. `Plan.warnings`,
telemetry privacy, and account deletion with `planned_meal.meal_id ON DELETE RESTRICT`."""

import uuid
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Meal, MealItem
from app.seed import run_seed
from tests.conftest import JsonLogs, captured_telemetry, make_settings
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, signup_body
from tests.integration.conftest import alembic_config
from tests.integration.test_onboarding import ONBOARD, PLAN, metric_body, onboarding, profile_body

FOODS = "/api/v1/foods"
MEALS = "/api/v1/meals"
MARKER = "qamarker-meal-zz9"


@pytest.fixture
def athlete(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    return api


def _wipe_seed_meals(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        session.execute(delete(MealItem))
        session.execute(delete(Meal))
        session.commit()


def _seed_food_id(api: Api) -> str:
    """A seed food (no owner): a meal built on it involves no custom-food RESTRICT (#131)."""
    with api.app.state.engine.connect() as c:
        food_id = c.execute(
            text("SELECT id FROM food WHERE owner_id IS NULL ORDER BY id LIMIT 1")
        ).scalar()
    return str(food_id)


def _custom_meal(client: TestClient, name: str, food_id: str | None = None) -> str:
    if food_id is not None:
        meal = client.post(
            MEALS,
            json={
                "name": name,
                "slots": ["breakfast", "lunch", "dinner", "snack"],
                "items": [{"food_id": food_id, "grams": 300}],
            },
        )
        assert meal.status_code == 201, meal.text
        return str(meal.json()["id"])
    food = client.post(
        FOODS,
        json={
            "name": f"{name} food",
            "kcal_per_100g": 200,
            "protein_g_per_100g": 20,
            "carbs_g_per_100g": 20,
            "fat_g_per_100g": 5,
            "diet_tags": [],
            "allergen_tags": [],
        },
    )
    assert food.status_code == 201, food.text
    meal = client.post(
        MEALS,
        json={
            "name": name,
            "slots": ["breakfast", "lunch", "dinner", "snack"],
            "items": [{"food_id": food.json()["id"], "grams": 300}],
        },
    )
    assert meal.status_code == 201, meal.text
    meal_id: str = meal.json()["id"]
    return meal_id


def _onboard(client: TestClient) -> dict[str, Any]:
    body = onboarding(profile_body(diet="omnivore", allergies=[], meals_per_day=3), metric_body())
    response = client.post(ONBOARD, json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _planned_meal_ids(result: dict[str, Any]) -> set[str]:
    return {m["meal"]["id"] for d in result["plan"]["meal_days"] for m in d["meals"]}


def _me_id(client: TestClient) -> uuid.UUID:
    return uuid.UUID(client.get("/api/v1/me").json()["id"])


def _second_user(api: Api, email: str) -> TestClient:
    client = api.new_client()
    response = client.post(
        "/api/v1/auth/signup", json=signup_body(email=email, display_name="Second")
    )
    assert response.status_code == 201, response.text
    return client


# ───────────── migration ─────────────


COUNTS = (
    "SELECT count(*) FROM users",
    "SELECT count(*) FROM plan",
    "SELECT count(*) FROM training_day",
    "SELECT count(*) FROM meal",
    "SELECT count(*) FROM meal_item",
    "SELECT count(*) FROM food",
    "SELECT count(*) FROM targets",
)


def test_migration_b4d7f1c9e203_round_trip_with_existing_data(athlete: Api) -> None:
    """downgrade -1 drops only the new tables with meal plan rows present; upgrade head works on a
    database that already holds users, plans and meals; Postgres 16."""
    _onboard(athlete.client)
    url = athlete.app.state.engine.url.render_as_string(hide_password=False)
    athlete.app.state.engine.dispose()
    engine = create_engine(url)
    with engine.connect() as c:
        assert c.execute(text("SHOW server_version")).scalar().startswith("16")  # type: ignore[union-attr]
        assert c.execute(text("SELECT count(*) FROM planned_meal")).scalar() == 21
        before = [c.execute(text(q)).scalar() for q in COUNTS]
    engine.dispose()

    command.downgrade(alembic_config(url), "a8c4e2f6b913")  # not "-1": later revisions sit on top
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "a8c4e2f6b913"
        assert c.execute(text("SELECT to_regclass('meal_day')")).scalar() is None
        assert c.execute(text("SELECT to_regclass('planned_meal')")).scalar() is None
        assert [c.execute(text(q)).scalar() for q in COUNTS] == before
    engine.dispose()

    command.upgrade(alembic_config(url), "b4d7f1c9e203")
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "b4d7f1c9e203"
        assert c.execute(text("SELECT count(*) FROM meal_day")).scalar() == 0
        assert [c.execute(text(q)).scalar() for q in COUNTS] == before
    engine.dispose()


# ───────────── library: own vs. stranger custom meals ─────────────


def test_own_custom_meal_is_used_and_a_strangers_never(athlete: Api) -> None:
    _wipe_seed_meals(athlete)
    stranger = _second_user(athlete, "bob@x.test")
    strangers_meal = _custom_meal(stranger, "Stranger meal")
    own_meal = _custom_meal(athlete.client, "Own meal")

    result = _onboard(athlete.client)

    used = _planned_meal_ids(result)
    assert own_meal in used
    assert strangers_meal not in used


def test_meal_warnings_stay_on_the_day_and_get_plan_equals_onboarding(athlete: Api) -> None:
    _wipe_seed_meals(athlete)
    result = _onboard(athlete.client)
    days = result["plan"]["meal_days"]
    assert all(d["warning"] for d in days)
    assert result["plan"]["warnings"] == []  # meal warnings are not copied to Plan.warnings
    assert athlete.client.get(PLAN).json() == result["plan"]


# ───────────── telemetry privacy (rule 6) ─────────────


def test_meal_plan_generation_leaks_no_meal_or_food_names(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, exporter, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    with TestClient(app) as client, Session(app.state.engine) as session:
        run_seed(session)
        session.execute(delete(MealItem))
        session.execute(delete(Meal))
        session.commit()
        assert client.post("/api/v1/auth/signup", json=signup_body()).status_code == 201
        meal_id = _custom_meal(client, MARKER)
        result = _onboard(client)
        assert meal_id in _planned_meal_ids(result)
        assert client.get(PLAN).status_code == 200

    spans = repr(
        [
            (s.name, dict(s.attributes or {}), [e.attributes for e in s.events])
            for s in exporter.get_finished_spans()
        ]
    )
    metrics = repr(reader.get_metrics_data())
    for blob in (spans, metrics, json_logs.text):
        assert MARKER not in blob
        assert "ana@x.test" not in blob


# ───────────── account deletion vs. planned_meal.meal_id RESTRICT ─────────────


def test_deleting_a_user_whose_custom_meal_is_in_their_own_plan(athlete: Api) -> None:
    """F18.2: a deleted user's own meals, plans and meal days all go. With
    `planned_meal.meal_id ON DELETE RESTRICT` the cascade users -> meal hits planned_meal rows
    that the users -> plan -> meal_day -> planned_meal cascade has not removed yet."""
    _wipe_seed_meals(athlete)
    own_meal = _custom_meal(athlete.client, "Own meal", _seed_food_id(athlete))
    assert own_meal in _planned_meal_ids(_onboard(athlete.client))
    user_id = _me_id(athlete.client)

    with athlete.app.state.engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    with athlete.app.state.engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}).scalar()
            == 0
        )
        assert c.execute(text("SELECT count(*) FROM planned_meal")).scalar() == 0


def test_deleting_a_user_whose_custom_meal_is_in_another_users_plan(athlete: Api) -> None:
    """Cross-user case (F18.4 analogue of D66): A's custom meal placed in B's plan (DB level, as
    a coach edit or plan copy could do once #47/F8 land). Deleting A must not fail."""
    _wipe_seed_meals(athlete)
    food_id = _seed_food_id(athlete)
    owner_meal = _custom_meal(athlete.client, "A meal", food_id)
    other = _second_user(athlete, "bob@x.test")
    _custom_meal(other, "B meal", food_id)
    _onboard(other)
    owner_id = _me_id(athlete.client)

    with athlete.app.state.engine.begin() as c:
        c.execute(
            text(
                "UPDATE planned_meal SET meal_id = :m WHERE id = "
                "(SELECT id FROM planned_meal ORDER BY id LIMIT 1)"
            ),
            {"m": uuid.UUID(owner_meal)},
        )
    with athlete.app.state.engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = :id"), {"id": owner_id})
    with athlete.app.state.engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": owner_id}).scalar()
            == 0
        )
