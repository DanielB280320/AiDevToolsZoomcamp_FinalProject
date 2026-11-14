"""D105 `createPlan` against real Postgres: empty and generated creation, the name and start date
carried to later versions, validation, authorization and the audit row (never the name)."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Plan, PlanChange, User
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem
from tests.integration.test_coach_dashboard import World, w  # noqa: F401  (fixture)
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
from tests.integration.test_plan_regenerate import athlete  # noqa: F401  (fixture)

TODAY = "2026-10-22"  # the test clock is Thursday 2026-10-22 09:00 UTC


def _create(client: Any, body: dict[str, Any], who: str = "me") -> Any:
    return client.post(f"{BASE}/athletes/{who}/plan", json=body)


def test_an_empty_plan_has_no_days_and_the_name_and_default_start_date(athlete: Api) -> None:  # noqa: F811
    first = _plan(athlete.client)
    assert first["name"] is None and first["start_date"] is None  # existing plans keep null
    response = _create(athlete.client, {"name": "  Summer cut  "})
    assert response.status_code == 201, response.text
    plan = response.json()
    assert_matches_schema(plan, "Plan")
    assert (plan["name"], plan["start_date"]) == ("Summer cut", TODAY)
    assert (plan["version"], plan["source"], plan["active"]) == (2, "custom", True)
    assert plan["revision"] == first["revision"] + 1
    assert plan["training_days"] == [] and plan["meal_days"] == []
    assert _plan(athlete.client)["name"] == "Summer cut"

    items = athlete.client.get(f"{ME}/plan/versions").json()["items"]
    assert_matches_schema(items[0], "PlanVersionSummary")
    assert [(v["version"], v["name"], v["active"]) for v in items] == [
        (2, "Summer cut", True),
        (1, None, False),
    ]
    assert athlete.client.get(f"{ME}/plan/versions/1").json()["training_days"]  # past stays

    with Session(athlete.app.state.engine) as session:
        row = session.scalars(select(Plan).where(Plan.version == 2)).one()
        change = session.scalars(select(PlanChange).where(PlanChange.plan_id == row.id)).one()
        assert change.change == {"kind": "created_new", "start_from": "empty"}
        assert change.author_role == "athlete"


def test_a_generated_plan_uses_the_profile_and_the_scope(athlete: Api) -> None:  # noqa: F811
    first = _plan(athlete.client)
    edited = _put(athlete.client, "training", _training_body(first)).json()
    response = _create(
        athlete.client,
        {"name": "Base", "start_date": "2026-10-19", "start_from": "generated", "scope": "meals"},
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert (plan["name"], plan["start_date"], plan["source"]) == ("Base", "2026-10-19", "generated")
    assert [d["name"] for d in plan["training_days"]] == [
        d["name"] for d in edited["training_days"]
    ]
    assert plan["meal_days"]
    full = _create(athlete.client, {"name": "All", "start_from": "generated"}).json()
    assert full["training_days"] and full["meal_days"]
    with Session(athlete.app.state.engine) as session:
        row = session.scalars(select(Plan).where(Plan.version == plan["version"])).one()
        change = session.scalars(select(PlanChange).where(PlanChange.plan_id == row.id)).one()
        assert change.change == {"kind": "created_new", "start_from": "generated"}


def test_name_and_start_date_are_carried_to_every_later_version(athlete: Api) -> None:  # noqa: F811
    created = _create(
        athlete.client, {"name": "Carry", "start_date": "2026-10-01", "start_from": "generated"}
    ).json()
    edited = _put(athlete.client, "training", _training_body(created)).json()
    assert (edited["name"], edited["start_date"]) == ("Carry", "2026-10-01")
    edited = _put(athlete.client, "meals", _meals_body(_plan(athlete.client))).json()
    assert (edited["name"], edited["start_date"]) == ("Carry", "2026-10-01")
    regenerated = athlete.client.post(f"{ME}/plan/regenerate").json()
    assert (regenerated["name"], regenerated["start_date"]) == ("Carry", "2026-10-01")
    items = athlete.client.get(f"{ME}/plan/versions").json()["items"]
    assert {v["name"] for v in items if v["version"] >= created["version"]} == {"Carry"}


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 61},
        {},
        {"name": "ok", "start_from": "nope"},
        {"name": "ok", "scope": "nope"},
        {"name": "ok", "extra": 1},
        {"name": "ok", "start_date": "not-a-date"},
    ],
)
def test_invalid_bodies_are_rejected_without_a_new_version(
    athlete: Api,  # noqa: F811
    body: dict[str, Any],
) -> None:
    problem(_create(athlete.client, body), 422, "validation_error")
    assert athlete.client.get(f"{ME}/plan/versions").json()["items"][0]["version"] == 1


def test_a_future_start_date_is_a_field_error_but_today_and_the_past_are_fine(
    athlete: Api,  # noqa: F811
) -> None:
    for start_from in ("empty", "generated"):
        response = _create(
            athlete.client, {"name": "Later", "start_date": "2026-10-23", "start_from": start_from}
        )
        body = problem(response, 422, "invalid_plan")
        assert [e["field"] for e in body["errors"]] == ["start_date"]
    assert athlete.client.get(f"{ME}/plan/versions").json()["items"][0]["version"] == 1
    assert _create(athlete.client, {"name": "T", "start_date": TODAY}).status_code == 201
    assert _create(athlete.client, {"name": "P", "start_date": "2020-01-01"}).status_code == 201


def test_the_start_date_default_and_limit_follow_the_athletes_time_zone(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    assert api.client.post(ONBOARD, json=onboarding()).status_code == 201
    with Session(api.app.state.engine) as session:
        session.scalars(select(User)).one().timezone = "Pacific/Honolulu"  # 23:00 Wed there
        session.commit()
    assert _create(api.client, {"name": "HI"}).json()["start_date"] == "2026-10-21"
    problem(_create(api.client, {"name": "HI", "start_date": TODAY}), 422, "invalid_plan")


def test_access_owner_unlinked_coach_stranger_and_not_onboarded(athlete: Api) -> None:  # noqa: F811
    ana = _user_id(athlete)
    stranger = athlete.new_client()
    assert stranger.post(f"{BASE}/auth/signup", json=_signup("bob@x.test")).status_code == 201
    coach = athlete.new_client()
    resp = coach.post(f"{BASE}/auth/signup", json=_signup("cora@x.test", "coach"))
    assert resp.status_code == 201
    for client in (stranger, coach):
        problem(_create(client, {"name": "Nope"}, str(ana)), 403, "not_linked")
    problem(_create(athlete.new_client(), {"name": "Nope"}, str(ana)), 401, "not_authenticated")
    assert _create(athlete.client, {"name": "Mine"}, str(ana)).status_code == 201
    fresh = athlete.new_client()
    assert fresh.post(f"{BASE}/auth/signup", json=_signup("new@x.test")).status_code == 201
    problem(_create(fresh, {"name": "x"}), 404, "not_onboarded")
    problem(_create(fresh, {"name": "x", "start_from": "generated"}), 404, "not_onboarded")


def test_a_linked_coach_can_create_a_plan_and_is_recorded_as_the_author(w: World) -> None:  # noqa: F811
    with Session(w.api.app.state.engine) as db:
        run_seed(db)
    ana = w.athlete("Ana")
    assert ana.client.post(ONBOARD, json=onboarding()).status_code == 201
    response = _create(w.cleo.client, {"name": "Coach plan"}, str(ana.id))
    assert response.status_code == 201, response.text
    assert response.json()["created_by"]["role"] == "coach"
    assert _plan(ana.client)["name"] == "Coach plan"
