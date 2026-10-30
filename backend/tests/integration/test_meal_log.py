"""#37 F12 meal logging API against real Postgres: eaten totals use logged quantities only
(F12.1), nutrition completion (F12.2), idempotent check-off (F12.3), adjust/skip/extra, Open Food
Facts import, authorization (owner / coach / stranger) and the check-off counter."""

import datetime as dt
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Exercise, Food, Meal, MealLog, MealLogItem, User
from app.seed import run_seed
from app.services.plans import (
    NewMealDay,
    NewPlannedExercise,
    NewPlannedMeal,
    NewTrainingDay,
    create_plan_version,
)
from tests.conftest import Captured, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fake_off import FakeOff, product
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem, signup_body

THU = "2026-10-22"  # NOW is Thursday 2026-10-22 09:00 UTC
FRI = "2026-10-23"
BASE = "/api/v1"
ME = f"{BASE}/athletes/me"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SLOTS = ("breakfast", "lunch", "dinner")


def _seed_athlete(api: Api, email: str = "ana@x.test") -> None:
    assert api.signup(email=email).status_code == 201
    with Session(api.app.state.engine) as session:
        run_seed(session)
        uid = session.scalars(select(User.id).where(User.email == email)).one()
        exercise = session.scalars(select(Exercise).where(Exercise.owner_id.is_(None))).first()
        meals = session.scalars(select(Meal).where(Meal.owner_id.is_(None)).order_by(Meal.name))
        picked = list(meals)[:3]
        assert exercise is not None and len(picked) == 3
        create_plan_version(
            session,
            athlete_id=uid,
            author_id=uid,
            source="generated",
            days=[
                NewTrainingDay(
                    "mon",
                    "Day",
                    [NewPlannedExercise(exercise.id, 3, 90, "linear", 2.5, reps_min=8, reps_max=8)],
                )
            ],
            meal_days=[
                NewMealDay(
                    w, [NewPlannedMeal(s, m.id, 1.0) for s, m in zip(SLOTS, picked, strict=True)]
                )
                for w in WEEKDAYS
            ],
            now=NOW - dt.timedelta(days=60),
        )
        session.commit()


@pytest.fixture
def athlete(api: Api) -> Api:
    _seed_athlete(api)
    return api


def _day(client: TestClient, day: str = THU) -> dict[str, Any]:
    response = client.get(f"{ME}/days/{day}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_matches_schema(body, "DayView")
    return body


def _post(client: TestClient, **body: Any) -> Any:
    return client.post(f"{ME}/meal-logs", json={"date": THU, **body})


def _food(api: Api, name: str = "Rice") -> str:
    with Session(api.app.state.engine) as session:
        food = session.scalars(
            select(Food).where(Food.source == "seed").order_by(Food.name)
        ).first()
        assert food is not None
        return str(food.id)


def _count(api: Api, model: Any) -> int:
    with Session(api.app.state.engine) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


# ───────────── F12.1 eaten uses logged quantities only ─────────────


def test_f12_1_eaten_counts_only_the_logged_meal(athlete: Api) -> None:
    day = _day(athlete.client)
    assert len(day["meals"]) == 3
    assert day["energy"]["eaten"]["kcal"] == 0
    assert day["energy"]["planned"]["kcal"] == sum(
        m["planned_meal"]["totals"]["kcal"] for m in day["meals"]
    )
    first = day["meals"][0]["planned_meal"]
    response = _post(athlete.client, planned_meal_id=first["id"], status="eaten")
    assert response.status_code == 201, response.text
    assert_matches_schema(response.json(), "MealLogResult")
    after = _day(athlete.client)
    assert after["energy"]["eaten"]["kcal"] == first["totals"]["kcal"]
    assert (
        after["energy"]["balance_kcal"]
        == first["totals"]["kcal"] - after["energy"]["burned"]["total_kcal"]
    )
    assert after["meals"][0]["log"]["status"] == "eaten"
    assert after["meals"][1]["log"] is None and after["meals"][2]["log"] is None
    assert [i["grams"] for i in after["meals"][0]["log"]["items"]] == [
        i["grams"] for i in first["items"]
    ]


def test_skipped_meal_adds_nothing_and_adjusted_uses_the_given_grams(athlete: Api) -> None:
    meals = [m["planned_meal"] for m in _day(athlete.client)["meals"]]
    skipped = _post(athlete.client, planned_meal_id=meals[0]["id"], status="skipped")
    assert skipped.status_code == 201
    assert skipped.json()["meal_log"]["items"] == []
    food = _food(athlete)
    adjusted = _post(
        athlete.client,
        planned_meal_id=meals[1]["id"],
        status="adjusted",
        items=[{"food_id": food, "grams": 100}],
    )
    assert adjusted.status_code == 201
    log = adjusted.json()["meal_log"]
    assert [i["grams"] for i in log["items"]] == [100]
    assert adjusted.json()["energy"]["eaten"]["kcal"] == log["totals"]["kcal"]


# ───────────── F12.2 completion ─────────────


def test_f12_2_completion_counts_eaten_and_adjusted_but_not_skipped(athlete: Api) -> None:
    meals = [m["planned_meal"] for m in _day(athlete.client)["meals"]]
    assert _day(athlete.client)["nutrition_completion"] == 0
    r = _post(athlete.client, planned_meal_id=meals[0]["id"], status="eaten")
    assert r.json()["nutrition_completion"] == pytest.approx(0.3333)
    _post(athlete.client, planned_meal_id=meals[1]["id"], status="skipped")
    assert _day(athlete.client)["nutrition_completion"] == pytest.approx(0.3333)
    r = _post(
        athlete.client,
        planned_meal_id=meals[2]["id"],
        status="adjusted",
        items=[{"food_id": _food(athlete), "grams": 50}],
    )
    assert r.json()["nutrition_completion"] == pytest.approx(0.6667)
    # Extra food is not a planned meal.
    r = _post(
        athlete.client,
        planned_meal_id=None,
        status="extra",
        slot="snack",
        items=[{"food_id": _food(athlete), "grams": 30}],
    )
    assert r.json()["nutrition_completion"] == pytest.approx(0.6667)


# ───────────── F12.3 idempotency ─────────────


def test_f12_3_repeated_checkoff_returns_existing_log_without_duplicates_or_count(
    migrated_database_url: str,
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, spans, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    captured = Captured(app, telemetry, spans, reader)
    with TestClient(app) as client:
        api = Api(app=app, client=client, clock=app.state.clock)
        _seed_athlete(api)
        planned = _day(client)["meals"][0]["planned_meal"]["id"]
        first = _post(client, planned_meal_id=planned, status="eaten")
        again = _post(client, planned_meal_id=planned, status="eaten")
        third = _post(client, planned_meal_id=planned, status="eaten")
        assert (first.status_code, again.status_code, third.status_code) == (201, 200, 200)
        assert first.json()["meal_log"]["id"] == again.json()["meal_log"]["id"]
        assert again.json()["meal_log"] == first.json()["meal_log"]
        assert _count(api, MealLog) == 1
        assert _count(api, MealLogItem) == len(first.json()["meal_log"]["items"])
        # Changing the decision replaces the same row; still not a new check-off.
        skipped = _post(client, planned_meal_id=planned, status="skipped")
        assert (
            skipped.status_code == 200
            and skipped.json()["meal_log"]["id"] == first.json()["meal_log"]["id"]
        )
        assert _count(api, MealLog) == 1
        other = _day(client)["meals"][1]["planned_meal"]["id"]
        assert _post(client, planned_meal_id=other, status="eaten").status_code == 201
    points = captured.metric_points("fitwise_meal_checkoffs_total")
    assert [p.value for p in points] == [2]
    assert all(not p.attributes for p in points)


def test_f12_3_concurrent_checkoffs_create_one_row(athlete: Api) -> None:
    planned = _day(athlete.client)["meals"][0]["planned_meal"]["id"]

    def check() -> int:
        return int(_post(athlete.client, planned_meal_id=planned, status="eaten").status_code)

    with ThreadPoolExecutor(4) as pool:
        codes = list(pool.map(lambda _: check(), range(4)))
    assert sorted(codes)[0] in (200, 201) and set(codes) <= {200, 201}
    assert _count(athlete, MealLog) == 1


# ───────────── extra food: library, custom, OFF ─────────────


def test_extra_food_from_library_and_custom_food_creates_extra_logs(athlete: Api) -> None:
    custom = athlete.client.post(
        f"{BASE}/foods",
        json={
            "name": "My bar",
            "kcal_per_100g": 400,
            "protein_g_per_100g": 20,
            "carbs_g_per_100g": 40,
            "fat_g_per_100g": 10,
        },
    )
    assert custom.status_code == 201
    library = _post(
        athlete.client,
        planned_meal_id=None,
        status="extra",
        slot="snack",
        items=[{"food_id": _food(athlete), "grams": 30}],
    )
    mine = _post(
        athlete.client,
        planned_meal_id=None,
        status="extra",
        items=[{"food_id": custom.json()["id"], "grams": 50}],
    )
    assert library.status_code == mine.status_code == 201
    assert mine.json()["meal_log"]["totals"]["kcal"] == 200
    assert mine.json()["meal_log"]["slot"] is None
    day = _day(athlete.client)
    assert {log["id"] for log in day["extra_meal_logs"]} == {
        library.json()["meal_log"]["id"],
        mine.json()["meal_log"]["id"],
    }
    assert day["energy"]["eaten"]["kcal"] == library.json()["meal_log"]["totals"]["kcal"] + 200
    # Extra food always creates: the same payload twice gives two rows.
    assert (
        _post(
            athlete.client,
            planned_meal_id=None,
            status="extra",
            items=[{"food_id": custom.json()["id"], "grams": 50}],
        ).status_code
        == 201
    )
    assert len(_day(athlete.client)["extra_meal_logs"]) == 3


def test_extra_food_from_an_open_food_facts_import(api_factory: Any, fake_off: FakeOff) -> None:
    fake_off.products = [product("8410000810004", "Greek yogurt 2%")]
    api: Api = api_factory(off_base_url=fake_off.base_url, off_timeout_seconds=0.4)
    _seed_athlete(api)
    imported = api.client.post(f"{BASE}/foods/import", json={"code": "8410000810004"})
    assert imported.status_code in (200, 201), imported.text
    response = _post(
        api.client,
        planned_meal_id=None,
        status="extra",
        slot="snack",
        items=[{"food_id": imported.json()["id"], "grams": 150}],
    )
    assert response.status_code == 201
    item = response.json()["meal_log"]["items"][0]
    assert item["food"]["source"] == "openfoodfacts" and item["grams"] == 150
    assert len(_day(api.client)["extra_meal_logs"]) == 1


# ───────────── delete / undo ─────────────


def test_delete_undoes_a_checkoff_and_lets_it_be_checked_off_again(athlete: Api) -> None:
    planned = _day(athlete.client)["meals"][0]["planned_meal"]["id"]
    log = _post(athlete.client, planned_meal_id=planned, status="eaten").json()["meal_log"]
    deleted = athlete.client.delete(f"{ME}/meal-logs/{log['id']}")
    assert deleted.status_code == 200
    assert_matches_schema(deleted.json(), "DayEnergyUpdate")
    assert deleted.json()["energy"]["eaten"]["kcal"] == 0
    assert deleted.json()["nutrition_completion"] == 0
    assert _count(athlete, MealLogItem) == 0
    assert _post(athlete.client, planned_meal_id=planned, status="eaten").status_code == 201
    problem(athlete.client.delete(f"{ME}/meal-logs/{uuid.uuid4()}"), 404, "meal_log_not_found")


# ───────────── history snapshots ─────────────


def test_a_log_keeps_its_grams_when_the_plan_is_replaced(athlete: Api) -> None:
    planned = _day(athlete.client)["meals"][0]["planned_meal"]
    log = _post(athlete.client, planned_meal_id=planned["id"], status="eaten").json()["meal_log"]
    with Session(athlete.app.state.engine) as session:
        uid = session.scalars(select(User.id)).one()
        exercise = session.scalars(select(Exercise)).first()
        assert exercise is not None
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
            now=NOW,
        )
        session.commit()
    day = _day(athlete.client)
    assert day["meals"] == []
    assert day["energy"]["eaten"]["kcal"] == log["totals"]["kcal"]


# ───────────── validation ─────────────


def test_validation_errors(athlete: Api) -> None:
    planned = _day(athlete.client)["meals"][0]["planned_meal"]["id"]
    food = _food(athlete)
    item = [{"food_id": food, "grams": 10}]
    for body in (
        {"planned_meal_id": planned, "status": "adjusted"},
        {"planned_meal_id": planned, "status": "eaten", "items": item},
        {"planned_meal_id": planned, "status": "extra", "items": item},
        {"planned_meal_id": None, "status": "extra"},
        {"planned_meal_id": None, "status": "eaten"},
        {
            "planned_meal_id": planned,
            "status": "adjusted",
            "items": [{"food_id": food, "grams": 0}],
        },
        {
            "planned_meal_id": planned,
            "status": "adjusted",
            "items": [{"food_id": food, "grams": 2001}],
        },
        {"planned_meal_id": planned, "status": "adjusted", "items": []},
        {"planned_meal_id": planned, "status": "bogus"},
    ):
        problem(_post(athlete.client, **body), 422, "validation_error")
    problem(
        athlete.client.post(
            f"{ME}/meal-logs", json={"date": FRI, "planned_meal_id": planned, "status": "eaten"}
        ),
        422,
        "date_in_future",
    )
    problem(
        _post(athlete.client, planned_meal_id=str(uuid.uuid4()), status="eaten"),
        404,
        "planned_meal_not_found",
    )
    problem(
        _post(
            athlete.client,
            planned_meal_id=planned,
            status="adjusted",
            items=[{"food_id": str(uuid.uuid4()), "grams": 5}],
        ),
        404,
        "food_not_found",
    )
    assert _count(athlete, MealLog) == 0


def test_a_past_day_can_be_logged_and_uses_that_days_plan(athlete: Api) -> None:
    wed = "2026-10-21"
    planned = _day(athlete.client, wed)["meals"][0]["planned_meal"]["id"]
    response = athlete.client.post(
        f"{ME}/meal-logs", json={"date": wed, "planned_meal_id": planned, "status": "eaten"}
    )
    assert response.status_code == 201
    assert _day(athlete.client, wed)["meals"][0]["log"]["status"] == "eaten"
    assert _day(athlete.client)["energy"]["eaten"]["kcal"] == 0


# ───────────── authorization ─────────────


def test_coach_and_stranger_cannot_write_or_delete_meal_logs(athlete: Api) -> None:
    planned = _day(athlete.client)["meals"][0]["planned_meal"]["id"]
    log = _post(athlete.client, planned_meal_id=planned, status="eaten").json()["meal_log"]
    me = athlete.client.get(f"{BASE}/me").json()["id"]
    stranger = athlete.new_client()
    assert (
        stranger.post(f"{BASE}/auth/signup", json=signup_body(email="bo@x.test")).status_code == 201
    )
    coach = athlete.new_client()
    assert (
        coach.post(
            f"{BASE}/auth/signup", json=signup_body(email="co@x.test", role="coach")
        ).status_code
        == 201
    )
    body = {"date": THU, "planned_meal_id": planned, "status": "eaten"}
    for who in (stranger, coach):
        problem(who.post(f"{BASE}/athletes/{me}/meal-logs", json=body), 403, "not_linked")
        problem(who.delete(f"{BASE}/athletes/{me}/meal-logs/{log['id']}"), 403, "not_linked")
    problem(coach.post(f"{ME}/meal-logs", json=body), 403, "not_linked")
    # A stranger's own scope cannot reach someone else's log.
    problem(stranger.delete(f"{ME}/meal-logs/{log['id']}"), 404, "meal_log_not_found")
    assert athlete.new_client().post(f"{ME}/meal-logs", json=body).status_code == 401
    assert _count(athlete, MealLog) == 1
