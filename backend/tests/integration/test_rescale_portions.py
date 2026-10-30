"""#171 D74: a targets change rescales meal portions from today on (recalc accept, profile edit,
calories accept); past days, meal keys and today's logs are untouched."""

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import MealDay, Plan, PlanChange, PlannedMeal, Suggestion, Targets, User
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api, problem, signup_body
from tests.integration.test_onboarding import (
    ONBOARD,
    PROFILE,
    metric_body,
    onboarding,
    profile_body,
)

ME = "/api/v1/athletes/me"
BM = f"{ME}/body-metrics"
TODAY = "2026-10-22"  # Thursday
PAST = ("2026-10-20", "2026-10-21")
FUTURE = ("2026-10-23", "2026-10-24", "2026-10-29")  # the last one is next Thursday


@pytest.fixture
def athlete(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    r = api.client.post(ONBOARD, json=onboarding(metric=metric_body(weight_kg=72.5)))
    assert r.status_code == 201, r.text
    with Session(api.app.state.engine) as session:  # the plan is older than the days we compare
        session.execute(update(Plan).values(created_at=NOW - dt.timedelta(days=60)))
        session.commit()
    return api


def _day(api: Api, day: str) -> dict[str, Any]:
    r = api.client.get(f"{ME}/days/{day}")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert_matches_schema(body, "DayView")
    return body


def _shape(api: Api, day: str) -> list[Any]:
    return [
        (
            m["planned_meal"]["slot"],
            m["planned_meal"]["meal"]["id"],
            [(i["food"]["id"], i["grams"]) for i in m["planned_meal"]["items"]],
            m["planned_meal"]["totals"],
        )
        for m in _day(api, day)["meals"]
    ]


def _planned_kcal(api: Api, day: str) -> int:
    return int(_day(api, day)["energy"]["planned"]["kcal"])


def _target_kcal(api: Api) -> int:
    return int(api.client.get(f"{ME}/targets", params={"date": TODAY}).json()["kcal"])


def _identity(api: Api, active_only: bool = True) -> dict[str, list[tuple[str, str, str]]]:
    """(slot, meal_id, meal_key) per weekday of the active plan."""
    with Session(api.app.state.engine) as db:
        plan = db.scalars(select(Plan).where(Plan.active.is_(True))).one()
        return {
            d.weekday: [
                (m.slot, str(m.meal_id), str(m.meal_key))
                for m in sorted(d.meals, key=lambda m: m.position)
            ]
            for d in plan.meal_days
        }


def _versions(api: Api) -> int:
    with Session(api.app.state.engine) as db:
        return int(db.scalar(select(func.count()).select_from(Plan)) or 0)


def _recalc_accept(api: Api) -> Any:
    s = api.client.post(BM, json={"date": TODAY, "weight_kg": 78.0}).json()["recalc_suggestion"]
    assert s is not None
    return api.client.post(f"/api/v1/suggestions/{s['id']}/accept")


def _profile_edit(api: Api) -> Any:
    return api.client.put(PROFILE, json=profile_body(goal="muscle_gain"))


def _calories_accept(api: Api, overrides: dict[str, Any] | None = None) -> Any:
    with Session(api.app.state.engine) as db:
        uid = db.scalars(select(User.id)).one()
        current = _target_kcal(api)
        row = Suggestion(
            athlete_id=uid,
            kind="calories",
            status="pending",
            rule="adaptive_calories",
            reason="test",
            inputs={},
            payload={
                "current_kcal": current,
                "proposed_kcal": current + 150,
                "delta_kcal": 150,
                "floor_applied": False,
                "expected_weekly_change_pct": 0.5,
                "tolerance_pct": 0.25,
                "observed_weekly_change_pct": [0.0, 0.0],
                "applied_kcal": None,
            },
            created_at=NOW,
        )
        db.add(row)
        db.commit()
        sid = row.id
    body = None if overrides is None else {"overrides": overrides}
    return api.client.post(f"/api/v1/suggestions/{sid}/accept", json=body)


def _rescale_check(api: Api, trigger: Any, reason: str) -> None:
    before_identity = _identity(api)
    past_before = {d: _shape(api, d) for d in PAST}
    old_future = _planned_kcal(api, "2026-10-23")
    versions = _versions(api)
    response = trigger(api)
    assert response.status_code == 200, response.text
    target = _target_kcal(api)
    assert _versions(api) == versions + 1
    # future days follow the new target (portions are rounded to 2 decimals)
    for day in (*FUTURE, TODAY):
        assert _planned_kcal(api, day) == pytest.approx(target, rel=0.03), day
    assert _planned_kcal(api, "2026-10-23") != old_future
    # past days unchanged
    assert {d: _shape(api, d) for d in PAST} == past_before
    # keys and meals carried forward
    assert _identity(api) == before_identity
    with Session(api.app.state.engine) as db:
        plan = db.scalars(select(Plan).where(Plan.active.is_(True))).one()
        change = db.scalars(select(PlanChange).where(PlanChange.plan_id == plan.id)).one()
        assert change.change == {"kind": "portions_rescaled", "reason": reason, "days": 7}
        assert change.author_id == plan.athlete_id
        assert plan.source == "generated"
        assert all(0 < m.portion_factor <= 3 for d in plan.meal_days for m in d.meals)


def test_recalc_accept_rescales_future_days(athlete: Api) -> None:
    _rescale_check(athlete, _recalc_accept, "recalc")


def test_profile_edit_rescales_future_days(athlete: Api) -> None:
    _rescale_check(athlete, _profile_edit, "profile")


def test_calories_accept_rescales_future_days(athlete: Api) -> None:
    _rescale_check(athlete, _calories_accept, "calories")


def test_calories_edit_then_accept_uses_the_override(athlete: Api) -> None:
    before = _target_kcal(athlete)
    response = _calories_accept(athlete, {"kcal": before + 300})
    assert response.status_code == 200, response.text
    assert_matches_schema(response.json(), "Suggestion")
    assert response.json()["payload"]["applied_kcal"] == before + 300
    assert _target_kcal(athlete) == before + 300
    assert _planned_kcal(athlete, "2026-10-23") == pytest.approx(before + 300, rel=0.03)


def test_calories_override_below_the_floor_is_422_and_changes_nothing(athlete: Api) -> None:
    with Session(athlete.app.state.engine) as db:
        db.execute(update(Targets).values(floor_kcal=2500))
        db.commit()
    versions = _versions(athlete)
    kcal = _target_kcal(athlete)
    problem(_calories_accept(athlete, {"kcal": 2400}), 422, "invalid_overrides")
    assert _versions(athlete) == versions
    assert _target_kcal(athlete) == kcal
    with Session(athlete.app.state.engine) as db:
        assert db.scalars(select(Suggestion.status)).one() == "pending"


def test_calories_override_for_other_fields_is_422(athlete: Api) -> None:
    problem(_calories_accept(athlete, {"reps_min": 5}), 422, "invalid_overrides")


def test_logged_meals_keep_their_logs_and_grams(athlete: Api) -> None:
    thu = _day(athlete, TODAY)
    first, second = thu["meals"][0]["planned_meal"], thu["meals"][1]["planned_meal"]
    wed = _day(athlete, PAST[1])
    wed_meal = wed["meals"][0]["planned_meal"]
    r = athlete.client.post(
        f"{ME}/meal-logs",
        json={"date": PAST[1], "planned_meal_id": wed_meal["id"], "status": "eaten"},
    )
    assert r.status_code == 201, r.text
    r = athlete.client.post(
        f"{ME}/meal-logs", json={"date": TODAY, "planned_meal_id": first["id"], "status": "eaten"}
    )
    assert r.status_code == 201, r.text
    logged = r.json()["meal_log"] if "meal_log" in r.json() else r.json()
    eaten_before = _day(athlete, TODAY)["energy"]["eaten"]["kcal"]
    past_before = _shape(athlete, PAST[1])
    assert _profile_edit(athlete).status_code == 200
    after = _day(athlete, TODAY)
    assert after["energy"]["eaten"]["kcal"] == eaten_before  # not double counted
    log = after["meals"][0]["log"]
    assert log is not None and log["status"] == "eaten"
    assert [i["grams"] for i in log["items"]] == [i["grams"] for i in first["items"]]
    assert log["id"] == logged["id"]
    # the unlogged meal of today is rescaled
    new_second = after["meals"][1]
    assert new_second["log"] is None
    assert [i["grams"] for i in new_second["planned_meal"]["items"]] != [
        i["grams"] for i in second["items"]
    ]
    # the past day keeps both its meals and its log
    assert _shape(athlete, PAST[1]) == past_before
    assert _day(athlete, PAST[1])["meals"][0]["log"]["status"] == "eaten"
    assert _day(athlete, PAST[1])["energy"]["eaten"]["kcal"] > 0


def test_no_meal_days_updates_targets_without_a_new_version(athlete: Api) -> None:
    with Session(athlete.app.state.engine) as db:
        db.execute(delete(PlannedMeal))
        db.execute(delete(MealDay))
        db.commit()
    versions = _versions(athlete)
    kcal = _target_kcal(athlete)
    assert _profile_edit(athlete).status_code == 200
    assert _target_kcal(athlete) != kcal
    assert _versions(athlete) == versions


def test_profile_edit_without_a_target_change_makes_no_version(athlete: Api) -> None:
    versions = _versions(athlete)
    assert athlete.client.put(PROFILE, json=profile_body(days_per_week=3)).status_code == 200
    assert _versions(athlete) == versions


def test_custom_plan_is_rescaled_by_portions_only(athlete: Api) -> None:
    plan = athlete.client.get(f"{ME}/plan").json()
    days = plan["meal_days"]
    # a hand edit makes the plan custom (same meals, one portion changed)
    body = {
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
            for d in days
        ],
    }
    edit = athlete.client.put(f"{ME}/plan/meals", json=body)
    assert edit.status_code == 200, edit.text
    identity = _identity(athlete)
    assert _profile_edit(athlete).status_code == 200
    assert _identity(athlete) == identity
    with Session(athlete.app.state.engine) as db:
        assert db.scalars(select(Plan.source).where(Plan.active.is_(True))).one() == "custom"


def test_coach_cannot_edit_the_profile(athlete: Api) -> None:
    coach = athlete.new_client()
    created = coach.post("/api/v1/auth/signup", json=signup_body(email="c@x.test", role="coach"))
    assert created.status_code == 201
    problem(coach.put(PROFILE, json=profile_body(goal="muscle_gain")), 403, "wrong_role")


def test_calories_accept_is_forbidden_for_strangers_and_coaches_and_changes_nothing(
    athlete: Api,
) -> None:
    """QA #178: only the suggestion's owner reaches the rescale (same rule as every accept)."""
    with Session(athlete.app.state.engine) as db:
        uid = db.scalars(select(User.id)).one()
        row = Suggestion(
            athlete_id=uid,
            kind="calories",
            status="pending",
            rule="adaptive_calories",
            reason="test",
            inputs={},
            payload={"current_kcal": 2000, "proposed_kcal": 2200, "applied_kcal": None},
            created_at=NOW,
        )
        db.add(row)
        db.commit()
        sid = row.id
    versions, kcal = _versions(athlete), _target_kcal(athlete)
    for email, role in (("bo@x.test", "athlete"), ("coach@x.test", "coach")):
        other = athlete.new_client()
        r = other.post("/api/v1/auth/signup", json=signup_body(email=email, role=role))
        assert r.status_code == 201
        problem(other.post(f"/api/v1/suggestions/{sid}/accept"), 403, "not_linked")
    assert _versions(athlete) == versions
    assert _target_kcal(athlete) == kcal
    with Session(athlete.app.state.engine) as db:
        assert db.scalars(select(Suggestion.status)).one() == "pending"
