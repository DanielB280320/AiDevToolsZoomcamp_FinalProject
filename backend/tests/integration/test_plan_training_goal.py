"""D107 plan training goal against real Postgres: the default from the profile goal, creation with a
goal, edit with the training update, carry-over to every later version, null resolution (rollback
safety), validation and authorization (owner, linked coach, stranger)."""

from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AthleteProfile, Plan
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem
from tests.integration.test_coach_dashboard import World, w  # noqa: F401  (fixture)
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_plan_create import _create
from tests.integration.test_plan_editor import (
    BASE,
    ME,
    _meals_body,
    _plan,
    _put,
    _signup,
    _training_body,
)
from tests.integration.test_plan_regenerate import athlete  # noqa: F401  (fixture)

RANGES = {
    "strength": (3, 6),
    "hypertrophy": (8, 12),
    "endurance": (13, 20),
    "maintenance": (6, 12),
    "cutting": (8, 12),
}


def _goal_body(plan: dict[str, Any], goal: str | None) -> dict[str, Any]:
    body = _training_body(plan)
    if goal is not None:
        body["training_goal"] = goal
    return body


def test_onboarding_plan_gets_the_goal_derived_from_the_profile_goal(athlete: Api) -> None:  # noqa: F811
    plan = _plan(athlete.client)  # the test profile's goal is cutting
    assert_matches_schema(plan, "Plan")
    assert plan["training_goal"] == "cutting"
    assert {k: (v["reps_min"], v["reps_max"]) for k, v in plan["rep_ranges"].items()} == RANGES
    with Session(athlete.app.state.engine) as session:
        assert session.scalars(select(Plan.training_goal)).one() == "cutting"


@pytest.mark.parametrize(
    ("profile_goal", "expected"),
    [
        ("muscle_gain", "hypertrophy"),
        ("cutting", "cutting"),
        ("maintenance", "maintenance"),
        ("recomposition", "hypertrophy"),
        ("wellness", "endurance"),
    ],
)
def test_a_new_plan_defaults_from_the_profile_goal(
    athlete: Api,  # noqa: F811
    profile_goal: str,
    expected: str,
) -> None:
    with Session(athlete.app.state.engine) as session:
        session.execute(update(AthleteProfile).values(goal=profile_goal))
        session.commit()
    created = _create(athlete.client, {"name": "Default"}).json()
    assert created["training_goal"] == expected


def test_a_new_plan_takes_the_chosen_goal_and_the_profile_goal_is_untouched(
    athlete: Api,  # noqa: F811
) -> None:
    for start_from in ("empty", "generated"):
        created = _create(
            athlete.client,
            {"name": "Mine", "training_goal": "strength", "start_from": start_from},
        )
        assert created.status_code == 201, created.text
        assert created.json()["training_goal"] == "strength"
    assert athlete.client.get(f"{ME}/profile").json()["goal"] == "cutting"


def test_the_goal_can_be_changed_with_the_training_update_and_is_kept_when_omitted(
    athlete: Api,  # noqa: F811
) -> None:
    plan = _plan(athlete.client)
    changed = _put(athlete.client, "training", _goal_body(plan, "endurance"))
    assert changed.status_code == 200, changed.text
    assert changed.json()["training_goal"] == "endurance"
    again = _put(athlete.client, "training", _goal_body(changed.json(), None))
    assert again.json()["training_goal"] == "endurance"
    cleared = _put(
        athlete.client, "training", {**_goal_body(again.json(), None), "training_goal": None}
    )
    assert cleared.json()["training_goal"] == "endurance"  # null means "unchanged"
    assert _plan(athlete.client)["training_goal"] == "endurance"


def test_the_goal_is_carried_to_every_later_version(athlete: Api) -> None:  # noqa: F811
    created = _create(
        athlete.client, {"name": "Carry", "training_goal": "strength", "start_from": "generated"}
    ).json()
    edited = _put(athlete.client, "training", _goal_body(created, None)).json()
    assert edited["training_goal"] == "strength"
    edited = _put(athlete.client, "meals", _meals_body(_plan(athlete.client))).json()
    assert edited["training_goal"] == "strength"
    regenerated = athlete.client.post(f"{ME}/plan/regenerate").json()
    assert regenerated["training_goal"] == "strength"
    old = athlete.client.get(f"{ME}/plan/versions/1").json()
    assert old["training_goal"] == "cutting"  # the earlier plan keeps its own


def test_a_null_goal_resolves_to_the_profile_goal_default(athlete: Api) -> None:  # noqa: F811
    """A row the previous release wrote (null) reads with the default, so a rollback is safe."""
    with Session(athlete.app.state.engine) as session:
        session.execute(update(Plan).values(training_goal=None))
        session.commit()
    plan = _plan(athlete.client)
    assert plan["training_goal"] == "cutting"
    edited = _put(athlete.client, "training", _goal_body(plan, None)).json()
    assert edited["training_goal"] == "cutting"
    with Session(athlete.app.state.engine) as session:
        assert session.scalars(select(Plan.training_goal).where(Plan.active)).one() is None


@pytest.mark.parametrize("goal", ["bulk", "", "Strength", 3])
def test_an_unknown_goal_is_rejected(athlete: Api, goal: Any) -> None:  # noqa: F811
    plan = _plan(athlete.client)
    problem(
        _put(athlete.client, "training", {**_training_body(plan), "training_goal": goal}),
        422,
        "validation_error",
    )
    problem(_create(athlete.client, {"name": "x", "training_goal": goal}), 422, "validation_error")
    assert _plan(athlete.client)["revision"] == plan["revision"]


def test_access_owner_coach_and_stranger(w: World) -> None:  # noqa: F811
    with Session(w.api.app.state.engine) as db:
        run_seed(db)
    ana = w.athlete("Ana")
    assert ana.client.post(ONBOARD, json=onboarding()).status_code == 201
    plan = _plan(ana.client)
    # a linked coach edits the goal and is recorded as the author
    coached = _put(w.cleo.client, "training", _goal_body(plan, "strength"), str(ana.id))
    assert coached.status_code == 200, coached.text
    assert coached.json()["training_goal"] == "strength"
    # a stranger cannot read or change it
    stranger = w.api.new_client()
    assert stranger.post(f"{BASE}/auth/signup", json=_signup("eve@x.test")).status_code == 201
    problem(
        _put(stranger, "training", _goal_body(coached.json(), "endurance"), str(ana.id)),
        403,
        "not_linked",
    )
    problem(stranger.get(f"{BASE}/athletes/{ana.id}/plan"), 403, "not_linked")
    assert _plan(ana.client)["training_goal"] == "strength"
