"""#180: a linked coach lists, accepts, rejects and edit-then-accepts suggestions (F11, F14, F16).

Runs for the three kinds (progression, recalc, calories) against real Postgres through the
`x-fitwise-access` dependency of #47. The owner and the linked coach get identical effects; a
pending, declined, ended or missing link and a stranger get 403 `not_linked` and change nothing.
"""

import itertools
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Plan, PlanChange, PlannedExercise, Suggestion, TrainingDay
from tests.integration.auth_helpers import NOW, problem
from tests.integration.test_authorization_matrix import (
    API,
    Person,
    World,
    fingerprint,
    new_suggestion,
    world,  # noqa: F401  (module fixture reused)
)

KINDS = ("progression", "recalc", "calories")
_weights = itertools.count(1)


def _targets(w: World) -> dict[str, Any]:
    r = w.ana.client.get(f"{API}/athletes/me/targets", params={"date": NOW.date().isoformat()})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _make_recalc(w: World) -> str:
    weight = round(72.5 * (1 + 0.06 * next(_weights)), 1)
    r = w.ana.client.post(
        f"{API}/athletes/me/body-metrics",
        json={"date": NOW.date().isoformat(), "weight_kg": weight},
    )
    assert r.status_code in (200, 201), r.text
    suggestion = r.json()["recalc_suggestion"]
    assert suggestion is not None, "a weight change above 2% proposes a recalculation"
    return str(suggestion["id"])


def _make_calories(w: World) -> str:
    current = int(_targets(w)["kcal"])
    with Session(w.engine) as db:
        row = Suggestion(
            athlete_id=w.ana.id,
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
        return str(row.id)


MAKERS: dict[str, Callable[[World], str]] = {
    "progression": new_suggestion,
    "recalc": _make_recalc,
    "calories": _make_calories,
}


def _row(w: World, suggestion_id: str) -> Suggestion:
    with Session(w.engine) as db:
        row = db.get(Suggestion, uuid.UUID(suggestion_id))
        assert row is not None
        db.expunge(row)
        return row


def _coach_authored_changes(w: World) -> int:
    with Session(w.engine) as db:
        return int(
            db.scalar(
                select(func.count())
                .select_from(PlanChange)
                .where(PlanChange.author_id == w.cleo.id, PlanChange.author_role == "coach")
            )
            or 0
        )


def _plan_versions(w: World) -> int:
    with Session(w.engine) as db:
        return int(db.scalar(select(func.count()).select_from(Plan)) or 0)


def _who(w: World) -> dict[str, Person]:
    return {
        "owner": w.ana,
        "stranger": w.bob,
        "never_linked": w.dan,
        "pending": w.eve,
        "declined": w.fay,
        "ended": w.gus,
    }


# ───────────── list ─────────────


@pytest.mark.parametrize("kind", KINDS)
def test_linked_coach_lists_the_athletes_suggestions_like_the_owner(
    world: World,  # noqa: F811
    kind: str,
) -> None:
    sid = MAKERS[kind](world)
    params = {"kind": kind}
    owner = world.ana.client.get(f"{API}/athletes/me/suggestions", params=params)
    coach = world.cleo.client.get(f"{API}/athletes/{world.ana.id}/suggestions", params=params)
    assert owner.status_code == coach.status_code == 200, coach.text
    assert sid in {i["id"] for i in coach.json()["items"]}
    assert coach.json()["items"] == owner.json()["items"]


@pytest.mark.parametrize("who", ["stranger", "never_linked", "pending", "declined", "ended"])
def test_list_is_403_not_linked_without_an_active_link(world: World, who: str) -> None:  # noqa: F811
    r = _who(world)[who].client.get(f"{API}/athletes/{world.ana.id}/suggestions")
    problem(r, 403, "not_linked")


# ───────────── decide as the linked coach ─────────────


@pytest.mark.parametrize("kind", KINDS)
def test_coach_accept_records_the_coach_as_decider_and_author(
    world: World,  # noqa: F811
    kind: str,
) -> None:
    sid = MAKERS[kind](world)
    r = world.cleo.client.post(f"{API}/suggestions/{sid}/accept")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"
    row = _row(world, sid)
    assert row.status == "accepted" and row.decided_by == world.cleo.id
    assert row.athlete_id == world.ana.id
    with Session(world.engine) as db:  # every change the coach made is authored as `coach`
        roles = set(
            db.scalars(select(PlanChange.author_role).where(PlanChange.author_id == world.cleo.id))
        )
    assert roles <= {"coach"}


def test_coach_accept_of_calories_sets_the_athletes_targets(world: World) -> None:  # noqa: F811
    sid = _make_calories(world)
    current = int(_targets(world)["kcal"])
    r = world.cleo.client.post(f"{API}/suggestions/{sid}/accept")
    assert r.status_code == 200, r.text
    assert r.json()["payload"]["applied_kcal"] == current + 150
    assert int(_targets(world)["kcal"]) == current + 150


def test_coach_calories_accept_rescales_portions_with_a_coach_change(
    world: World,  # noqa: F811
) -> None:
    sid = _make_calories(world)
    versions, before = _plan_versions(world), _coach_authored_changes(world)
    assert world.cleo.client.post(f"{API}/suggestions/{sid}/accept").status_code == 200
    # D74: the plan has meal days, so portions move to a new plan version authored by the coach.
    assert _plan_versions(world) == versions + 1
    assert _coach_authored_changes(world) > before


def test_coach_edit_then_accept_calories_applies_the_override(world: World) -> None:  # noqa: F811
    sid = _make_calories(world)
    current = int(_targets(world)["kcal"])
    r = world.cleo.client.post(
        f"{API}/suggestions/{sid}/accept", json={"overrides": {"kcal": current + 50}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["payload"]["applied_kcal"] == current + 50
    assert int(_targets(world)["kcal"]) == current + 50
    assert _row(world, sid).decided_by == world.cleo.id


def test_coach_accept_of_recalc_stores_the_proposed_targets(world: World) -> None:  # noqa: F811
    sid = _make_recalc(world)
    proposed = _row(world, sid).inputs["proposed_targets"]["kcal"]
    r = world.cleo.client.post(f"{API}/suggestions/{sid}/accept")
    assert r.status_code == 200, r.text
    assert int(_targets(world)["kcal"]) == proposed
    assert _row(world, sid).decided_by == world.cleo.id


def test_coach_edit_then_accept_progression_applies_the_override(world: World) -> None:  # noqa: F811
    sid = new_suggestion(world)
    timed = _row(world, sid).payload["exercise"]["type"] == "timed"
    overrides = {"target_seconds": 45} if timed else {"target_weight_kg": 25}
    versions, before = _plan_versions(world), _coach_authored_changes(world)
    r = world.cleo.client.post(f"{API}/suggestions/{sid}/accept", json={"overrides": overrides})
    assert r.status_code == 200, r.text
    assert _plan_versions(world) == versions + 1
    assert _coach_authored_changes(world) > before
    assert _row(world, sid).decided_by == world.cleo.id


@pytest.mark.parametrize("kind", KINDS)
def test_coach_reject_changes_only_the_suggestion(world: World, kind: str) -> None:  # noqa: F811
    sid = MAKERS[kind](world)
    targets, versions = _targets(world), _plan_versions(world)
    r = world.cleo.client.post(f"{API}/suggestions/{sid}/reject")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    row = _row(world, sid)
    assert row.status == "rejected" and row.decided_by == world.cleo.id
    assert _targets(world) == targets
    assert _plan_versions(world) == versions


def test_deciding_twice_is_409_and_keeps_the_coach_as_decider(world: World) -> None:  # noqa: F811
    sid = _make_calories(world)
    assert world.cleo.client.post(f"{API}/suggestions/{sid}/reject").status_code == 200
    problem(
        world.ana.client.post(f"{API}/suggestions/{sid}/accept"), 409, "suggestion_already_decided"
    )
    assert _row(world, sid).decided_by == world.cleo.id


# ───────────── owner and no active link ─────────────


@pytest.mark.parametrize("kind", KINDS)
def test_owner_still_accepts_and_is_recorded_as_decider(world: World, kind: str) -> None:  # noqa: F811
    sid = MAKERS[kind](world)
    r = world.ana.client.post(f"{API}/suggestions/{sid}/accept")
    assert r.status_code == 200, r.text
    assert _row(world, sid).decided_by == world.ana.id


@pytest.mark.parametrize("verb", ["accept", "reject"])
@pytest.mark.parametrize("who", ["stranger", "never_linked", "pending", "declined", "ended"])
@pytest.mark.parametrize("kind", KINDS)
def test_decide_without_an_active_link_is_403_and_changes_nothing(
    world: World,  # noqa: F811
    kind: str,
    who: str,
    verb: str,
) -> None:
    sid = MAKERS[kind](world)
    before = fingerprint(world.engine)
    r = _who(world)[who].client.post(f"{API}/suggestions/{sid}/{verb}")
    problem(r, 403, "not_linked")
    assert fingerprint(world.engine) == before
    assert _row(world, sid).status == "pending"


# ───────────── QA (#180): exact effects and authorship of a coach decision ─────────────


def _active_plan_and_changes(w: World) -> tuple[Plan, list[PlanChange]]:
    with Session(w.engine) as db:
        plan = db.scalar(select(Plan).where(Plan.athlete_id == w.ana.id, Plan.active.is_(True)))
        assert plan is not None
        changes = list(db.scalars(select(PlanChange).where(PlanChange.plan_id == plan.id)))
        db.expunge_all()
        return plan, changes


def _assert_coach_authored(w: World, plan: Plan, changes: list[PlanChange]) -> None:
    assert plan.created_by == w.cleo.id
    assert changes, "a new plan version records at least one PlanChange"
    assert {(c.author_id, c.author_role) for c in changes} == {(w.cleo.id, "coach")}


@pytest.mark.parametrize("overrides", [None, "edit"])
def test_qa_coach_progression_accept_writes_targets_to_a_coach_authored_version(
    world: World,  # noqa: F811
    overrides: str | None,
) -> None:
    sid = new_suggestion(world)
    row = _row(world, sid)
    timed = row.payload["exercise"]["type"] == "timed"
    expected: dict[str, Any] = dict(row.payload["proposed"])
    body: dict[str, Any] | None = None
    if overrides:
        edit = {"target_seconds": 47} if timed else {"target_weight_kg": 27.5}
        expected.update(edit)
        body = {"overrides": edit}
    versions = _plan_versions(world)
    r = world.cleo.client.post(f"{API}/suggestions/{sid}/accept", json=body)
    assert r.status_code == 200, r.text
    assert _plan_versions(world) == versions + 1
    plan, changes = _active_plan_and_changes(world)
    _assert_coach_authored(world, plan, changes)
    accepted = [c for c in changes if c.change.get("kind") == "suggestion_accepted"]
    assert [c.change.get("suggestion_id") for c in accepted] == [sid]
    assert len(changes) == 1, "one PlanChange row per decision (D65(3))"
    with Session(world.engine) as db:
        decided = db.get(Suggestion, uuid.UUID(sid))
        assert decided is not None and decided.planned_exercise_id is not None
        planned = db.get(PlannedExercise, decided.planned_exercise_id)
        assert planned is not None
        day = db.get(TrainingDay, planned.training_day_id)
        assert day is not None and day.plan_id == plan.id
        keys = ("target_seconds",) if timed else ("target_weight_kg", "reps_min", "reps_max")
        for key in keys:
            got = getattr(planned, key)
            want = expected[key]
            assert (None if got is None else float(got)) == (
                None if want is None else float(want)
            ), key


@pytest.mark.parametrize("kind", ["recalc", "calories"])
def test_qa_coach_targets_accept_rescales_portions_in_one_coach_change(
    world: World,  # noqa: F811
    kind: str,
) -> None:
    sid = MAKERS[kind](world)
    versions = _plan_versions(world)
    r = world.cleo.client.post(f"{API}/suggestions/{sid}/accept")
    assert r.status_code == 200, r.text
    assert _plan_versions(world) == versions + 1  # D74: the plan has meal days
    plan, changes = _active_plan_and_changes(world)
    _assert_coach_authored(world, plan, changes)
    assert [c.change.get("kind") for c in changes] == ["portions_rescaled"]
    assert changes[0].change.get("reason") == kind


def test_qa_coach_recalc_rejects_overrides_and_stays_pending(world: World) -> None:  # noqa: F811
    sid = _make_recalc(world)
    before = fingerprint(world.engine)
    r = world.cleo.client.post(
        f"{API}/suggestions/{sid}/accept", json={"overrides": {"kcal": 2000}}
    )
    problem(r, 422, "invalid_overrides")
    assert fingerprint(world.engine) == before
    assert _row(world, sid).status == "pending"
