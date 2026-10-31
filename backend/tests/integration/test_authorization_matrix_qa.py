"""QA for #47: gaps around the authorization matrix.

* Every route the app serves is in `openapi.yaml`, so no endpoint can bypass the matrix by being
  left out of the contract.
* Every coach write on an `owner-or-coach` operation is authored by the coach (D75(3), D82(3)):
  training and meal edits, regeneration, and accepting/rejecting a suggestion.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PlanChange, Suggestion
from tests.integration.test_authorization_matrix import (
    API,
    OPERATIONS,
    World,
    new_suggestion,
    plan,
    world,  # noqa: F401  (module fixture reused)
)
from tests.integration.test_plan_editor import _meals_body


def test_every_served_route_is_in_the_contract(world: World) -> None:  # noqa: F811
    contract_ops = {(o.method, o.path) for o in OPERATIONS}
    served = {
        (method.upper(), path.removeprefix(API))
        for path, item in world.app.openapi()["paths"].items()
        if path.startswith(API)
        for method in item
    }
    missing = served - contract_ops
    assert not missing, f"served but not in openapi.yaml (not covered by the matrix): {missing}"


def _coach_changes(w: World) -> list[tuple[Any, Any]]:
    with Session(w.engine) as db:
        return [
            (c.author_id, c.author_role)
            for c in db.scalars(select(PlanChange).where(PlanChange.author_id == w.cleo.id))
        ]


def _assert_one_more_coach_change(w: World, before: int) -> None:
    after = _coach_changes(w)
    assert len(after) == before + 1, after
    assert all(role == "coach" for _, role in after)
    with Session(w.engine) as db:  # nothing is attributed to the coach as an athlete
        assert (
            db.scalar(
                select(func.count())
                .select_from(PlanChange)
                .where(PlanChange.author_id == w.cleo.id, PlanChange.author_role != "coach")
            )
            == 0
        )


def test_a_coach_meal_edit_is_authored_by_the_coach(world: World) -> None:  # noqa: F811
    before = len(_coach_changes(world))
    r = world.cleo.client.put(
        f"{API}/athletes/{world.ana.id}/plan/meals", json=_meals_body(plan(world))
    )
    assert r.status_code == 200, r.text
    _assert_one_more_coach_change(world, before)


def test_a_coach_regeneration_is_authored_by_the_coach(world: World) -> None:  # noqa: F811
    before = len(_coach_changes(world))
    r = world.cleo.client.post(
        f"{API}/athletes/{world.ana.id}/plan/regenerate", json={"scope": "training"}
    )
    assert 200 <= r.status_code < 300, r.status_code
    _assert_one_more_coach_change(world, before)


def test_a_coach_accept_is_decided_and_authored_by_the_coach(world: World) -> None:  # noqa: F811
    suggestion = new_suggestion(world)
    before = len(_coach_changes(world))
    r = world.cleo.client.post(f"{API}/suggestions/{suggestion}/accept")
    assert r.status_code == 200, r.text
    with Session(world.engine) as db:
        row = db.get(Suggestion, uuid.UUID(suggestion))
        assert row is not None
        assert row.status == "accepted"
        assert row.decided_by == world.cleo.id
        assert row.athlete_id == world.ana.id
    after = _coach_changes(world)
    assert len(after) >= before  # a `hold` changes no targets; any new change is the coach's
    assert all(role == "coach" for _, role in after)


def test_a_coach_reject_is_decided_by_the_coach(world: World) -> None:  # noqa: F811
    suggestion = new_suggestion(world)
    r = world.cleo.client.post(f"{API}/suggestions/{suggestion}/reject")
    assert r.status_code == 200, r.text
    with Session(world.engine) as db:
        row = db.get(Suggestion, uuid.UUID(suggestion))
        assert row is not None
        assert row.status == "rejected"
        assert row.decided_by == world.cleo.id
