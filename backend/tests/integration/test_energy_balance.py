"""#38 Daily energy balance (F13) against real Postgres: baseline and targets from the `Targets`
row valid on the day, stable past days, rest-day activities, the Week view and authorization."""

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Exercise, Targets, User
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api, problem, signup_body
from tests.integration.test_training_log import _seed_athlete

BASE = "/api/v1"
THU = "2026-10-22"
WED = "2026-10-21"  # rest day in the seeded plan (mon, thu, fri)


def _add_targets(api: Api, valid_from: dt.date, baseline: int, kcal: int, balance: int) -> None:
    with Session(api.app.state.engine) as db:
        uid = db.scalars(select(User.id)).first()
        assert uid is not None
        db.add(
            Targets(
                user_id=uid,
                valid_from=valid_from,
                bmr_formula="mifflin_st_jeor",
                bmr_kcal=baseline - 400,
                lifestyle_factor=1.4,
                baseline_kcal=baseline,
                planned_exercise_kcal_per_day=100,
                goal_adjustment_pct=-0.1,
                kcal=kcal,
                protein_g=150.5,
                carbs_g=200.0,
                fat_g=60.0,
                target_balance_kcal=balance,
                floor_applied=False,
                floor_kcal=1500,
                carbs_clamped=False,
                weight_used_kg=80,
                body_fat_pct_used=None,
                explanation="test",
                inputs={},
                created_at=NOW,
            )
        )
        db.commit()


@pytest.fixture
def athlete(api: Api) -> Api:
    _seed_athlete(api)
    _add_targets(api, dt.date(2026, 10, 1), baseline=2200, kcal=2000, balance=-300)
    return api


def _day(api: Api, day: str, client: Any = None) -> dict[str, Any]:
    response = (client or api.client).get(f"{BASE}/athletes/me/days/{day}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _activity(api: Api, day: str, minutes: int) -> dict[str, Any]:
    with Session(api.app.state.engine) as db:
        ex = db.scalars(
            select(Exercise.id).where(Exercise.owner_id.is_(None), Exercise.type == "timed")
        ).first()
    response = api.client.post(
        f"{BASE}/athletes/me/activities",
        json={"date": day, "exercise_id": str(ex), "minutes": minutes},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_day_energy_has_baseline_target_and_balance(athlete: Api) -> None:
    energy = _day(athlete, THU)["energy"]
    assert_matches_schema(energy, "EnergyBalance")
    assert energy["estimated"] is True
    assert energy["burned"] == {
        "total_kcal": 2200,
        "baseline_kcal": 2200,
        "training_kcal": 0,
        "activities_kcal": 0,
    }
    assert energy["balance_kcal"] == 0 - 2200
    assert energy["target"] == {
        "kcal": 2000,
        "protein_g": 150.5,
        "carbs_g": 200.0,
        "fat_g": 60.0,
    }
    assert energy["target_balance_kcal"] == -300


def test_rest_day_activity_adds_to_baseline(athlete: Api) -> None:
    kcal = _activity(athlete, WED, 60)["activity"]["kcal"]
    assert kcal > 0
    day = _day(athlete, WED)
    assert day["training_status"] == "rest"
    burned = day["energy"]["burned"]
    assert burned["activities_kcal"] == kcal
    assert burned["total_kcal"] == 2200 + kcal
    assert day["energy"]["balance_kcal"] == -(2200 + kcal)


def test_past_day_is_stable_after_new_targets(athlete: Api) -> None:
    _activity(athlete, WED, 30)
    before = _day(athlete, WED)["energy"]
    _add_targets(athlete, dt.date(2026, 10, 22), baseline=2600, kcal=2400, balance=-100)
    assert _day(athlete, WED)["energy"] == before
    # The new row applies from its own date on.
    assert _day(athlete, THU)["energy"]["burned"]["baseline_kcal"] == 2600
    assert _day(athlete, THU)["energy"]["target_balance_kcal"] == -100


def test_days_before_the_first_row_use_the_first_row(athlete: Api) -> None:
    assert _day(athlete, "2026-09-10")["energy"]["burned"]["baseline_kcal"] == 2200


def test_week_days_carry_the_day_view_energy(athlete: Api) -> None:
    _activity(athlete, WED, 45)
    response = athlete.client.get(
        f"{BASE}/athletes/me/calendar", params={"from": "2026-10-19", "to": "2026-10-25"}
    )
    assert response.status_code == 200, response.text
    assert_matches_schema(response.json(), "CalendarRange")
    days = response.json()["days"]
    assert len(days) == 7
    for day in days:
        assert day["energy"] == _day(athlete, day["date"])["energy"]
    empty = next(d for d in days if d["date"] == "2026-10-25")
    assert empty["energy"]["burned"]["total_kcal"] == 2200


def test_not_onboarded_athlete_has_zero_baseline(api: Api) -> None:
    _seed_athlete(api)
    energy = _day(api, THU)["energy"]
    assert energy["burned"]["baseline_kcal"] == 0
    assert energy["target"]["kcal"] == 0


def test_stranger_is_refused_and_owner_allowed(athlete: Api) -> None:
    owner_id = _day(athlete, THU)["energy"] and athlete.client.get(f"{BASE}/me").json()["id"]
    stranger = athlete.new_client()
    assert (
        stranger.post(f"{BASE}/auth/signup", json=signup_body(email="bo@x.test")).status_code == 201
    )
    problem(stranger.get(f"{BASE}/athletes/{owner_id}/days/{THU}"), 403, "not_linked")
    problem(
        stranger.get(
            f"{BASE}/athletes/{owner_id}/calendar",
            params={"from": "2026-10-19", "to": "2026-10-25"},
        ),
        403,
        "not_linked",
    )
    assert athlete.client.get(f"{BASE}/athletes/{owner_id}/days/{THU}").status_code == 200


def test_week_energy_matches_day_view_with_meals_logged(api: Api) -> None:
    """Eaten and planned in the range query equal the day view's (meal plan on every weekday)."""
    from tests.integration.test_meal_log import _seed_athlete as seed_with_meals

    seed_with_meals(api)
    _add_targets(api, dt.date(2026, 10, 1), baseline=2200, kcal=2000, balance=-300)
    for day in ("2026-10-20", THU):
        meals = _day(api, day)["meals"]
        for meal, status in zip(meals[:2], ("eaten", "skipped"), strict=False):
            response = api.client.post(
                f"{BASE}/athletes/me/meal-logs",
                json={"date": day, "planned_meal_id": meal["planned_meal"]["id"], "status": status},
            )
            assert response.status_code == 201, response.text
    response = api.client.get(
        f"{BASE}/athletes/me/calendar", params={"from": "2026-10-19", "to": "2026-10-25"}
    )
    days = response.json()["days"]
    for day in days:
        assert day["energy"] == _day(api, day["date"])["energy"]
    assert next(d for d in days if d["date"] == THU)["energy"]["eaten"]["kcal"] > 0
    assert next(d for d in days if d["date"] == THU)["energy"]["planned"]["kcal"] > 0


def test_range_matches_day_view_across_a_targets_change_and_before_first_row(athlete: Api) -> None:
    """QA: a Targets row starting mid-range (and days before the first row) match the day view."""
    _activity(athlete, WED, 30)
    _add_targets(athlete, dt.date(2026, 10, 22), baseline=2600, kcal=2400, balance=-100)
    response = athlete.client.get(
        f"{BASE}/athletes/me/calendar", params={"from": "2026-09-28", "to": "2026-11-08"}
    )
    assert response.status_code == 200, response.text
    days = response.json()["days"]
    assert len(days) == 42
    for day in days:
        assert day["energy"] == _day(athlete, day["date"])["energy"], day["date"]
    by_date = {d["date"]: d["energy"] for d in days}
    assert by_date["2026-09-30"]["burned"]["baseline_kcal"] == 2200  # before the first row
    assert by_date["2026-10-21"]["burned"]["baseline_kcal"] == 2200
    assert by_date["2026-10-22"]["burned"]["baseline_kcal"] == 2600
    assert by_date["2026-10-22"]["target_balance_kcal"] == -100
