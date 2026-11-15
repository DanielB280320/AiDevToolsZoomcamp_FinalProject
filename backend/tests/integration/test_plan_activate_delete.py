"""D108 against real Postgres: make a previous plan current (no version written, the active flag
moves to the plan's latest version) and delete a plan that is not current (soft delete). The
"active is not necessarily the highest version" invariant, numbering after both, side effects on
sessions and suggestions, past logs, and access (owner / linked coach / stranger)."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Plan, PlanChange, SetLog, Suggestion, TrainingSession
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api, problem
from tests.integration.test_coach_dashboard import World, w  # noqa: F401  (fixture)
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_plan_editor import (
    BASE,
    ME,
    _day,
    _meals_body,
    _plan,
    _put,
    _signup,
    _training_body,
    athlete,  # noqa: F401  (fixture)
)
from tests.integration.test_plan_history import _plans, _versions

THU = "2026-10-22"
FRI = "2026-10-23"


def _activate(client: Any, plan_no: int, who: str = "me") -> Any:
    return client.post(f"{BASE}/athletes/{who}/plans/{plan_no}/activate")


def _delete(client: Any, plan_no: int, who: str = "me") -> Any:
    return client.delete(f"{BASE}/athletes/{who}/plans/{plan_no}")


def _new(client: Any, name: str, **extra: Any) -> dict[str, Any]:
    response = client.post(f"{ME}/plan", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _edit(client: Any) -> dict[str, Any]:
    response = _put(client, "training", _training_body(_plan(client)))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _rows(api: Api) -> list[tuple[int, bool, int | None]]:
    with Session(api.app.state.engine) as db:
        rows = db.execute(select(Plan.version, Plan.active, Plan.plan_no).order_by(Plan.version))
        return [(r[0], r[1], r[2]) for r in rows]


def _logs(api: Api) -> list[tuple[Any, ...]]:
    with Session(api.app.state.engine) as db:
        return sorted(
            (str(s.session_id), s.set_no, s.target_reps, s.target_weight_kg, s.reps)
            for s in db.scalars(select(SetLog))
        )


def test_make_current_writes_no_version_and_moves_the_active_flag(athlete: Api) -> None:  # noqa: F811
    client = athlete.client
    _edit(client)  # plan 1: v1, v2
    second = _new(client, "Second")  # plan 2: v3
    _edit(client)  # plan 2: v4
    before_rows = _rows(athlete)
    before_list = _plans(client)
    with Session(athlete.app.state.engine) as db:
        changes = db.scalar(select(func.count()).select_from(PlanChange))

    response = _activate(client, 1)
    assert response.status_code == 200, response.text
    current = response.json()
    assert_matches_schema(current, "Plan")
    assert (current["version"], current["plan_no"], current["active"]) == (2, 1, True)
    assert current["revision"] > second["revision"] + 1  # a stale editor is refused

    after_rows = _rows(athlete)
    assert [(v, n) for v, _, n in after_rows] == [(v, n) for v, _, n in before_rows]
    assert [(v, a) for v, a, _ in after_rows] == [(1, False), (2, True), (3, False), (4, False)]
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(PlanChange)) == changes
    after_list = _plans(client)
    assert [(p["plan_no"], p["active"]) for p in after_list] == [(2, False), (1, True)]
    for old, new in zip(before_list, after_list, strict=True):
        assert {k: v for k, v in old.items() if k != "active"} == {
            k: v for k, v in new.items() if k != "active"
        }  # change counts and timelines untouched
    assert _plan(client)["version"] == 2

    again = _activate(client, 1)  # idempotent
    assert again.status_code == 200 and again.json() == current
    assert _rows(athlete) == after_rows


def test_the_next_edit_continues_the_chosen_plan_and_new_plans_are_numbered_after_the_highest(
    athlete: Api,  # noqa: F811
) -> None:
    client = athlete.client
    _edit(client)  # v2 (plan 1)
    _new(client, "Second")  # v3
    _edit(client)  # v4 (plan 2)
    stale = _training_body(_plan(client))  # plan 2's revision
    assert _activate(client, 1).status_code == 200
    problem(_put(client, "training", stale), 409, "plan_revision_conflict")

    edited = _edit(client)
    assert (edited["version"], edited["plan_no"], edited["name"]) == (5, 1, None)
    assert [(p["plan_no"], p["changes"], p["active"]) for p in _plans(client)] == [
        (2, 1, False),
        (1, 2, True),
    ]
    assert [v["version"] for v in _versions(client, 1)] == [5, 2, 1]

    third = _new(client, "Third")
    assert (third["version"], third["plan_no"]) == (6, 3)
    assert _activate(client, 2).status_code == 200
    renamed = _edit(client)
    assert (renamed["plan_no"], renamed["name"], renamed["version"]) == (2, "Second", 7)
    assert [p["plan_no"] for p in _plans(client)] == [3, 2, 1]


def test_activation_moves_future_sessions_rejects_pending_suggestions_and_keeps_the_past(
    athlete: Api,  # noqa: F811
) -> None:
    client = athlete.client
    first = _plan(client)
    thursday = _day(client, THU)["session"]
    exercise = thursday["exercises"][0]["exercise"]["id"]
    for n in (1, 2, 3):
        logged = client.post(
            f"{BASE}/sessions/{thursday['id']}/sets",
            json={"exercise_id": exercise, "set_no": n, "reps": 8, "weight_kg": 50},
        )
        assert logged.status_code in (200, 201), logged.text
    assert client.post(f"{BASE}/sessions/{thursday['id']}/finish", json=None).status_code == 200
    assert _day(client, FRI)["session"]["plan_version"] == 1  # untouched, on plan 1
    meal_keys = {m["planned_meal"]["meal_key"] for m in _day(client, THU)["meals"]}
    logs_before = _logs(athlete)

    athlete.clock.advance(minutes=5)
    _new(client, "Second")  # an empty plan: Friday's untouched session is dropped
    assert _day(client, FRI)["session"] is None
    second_body = _training_body(first)
    second_body["revision"] = _plan(client)["revision"]
    for d in second_body["training_days"]:
        d["id"] = None
        for e in d["exercises"]:
            e["id"] = None
    assert _put(client, "training", second_body).status_code == 200
    meals = _meals_body(first)
    meals["revision"] = _plan(client)["revision"]
    for d in meals["meal_days"]:
        for m in d["meals"]:
            m["id"] = None
    assert _put(client, "meals", meals).status_code == 200
    second = _plan(client)
    assert _day(client, FRI)["session"]["plan_version"] == second["version"]
    planned = second["training_days"][0]["exercises"][0]
    with Session(athlete.app.state.engine) as db:
        db.add(
            Suggestion(
                athlete_id=uuid.UUID(second["athlete_id"]),
                kind="progression",
                status="pending",
                rule="r",
                reason="r",
                inputs={},
                payload={"planned_exercise_id": planned["id"]},
                planned_exercise_id=uuid.UUID(planned["id"]),
                exercise_id=uuid.UUID(planned["exercise"]["id"]),
                created_at=NOW,
            )
        )
        db.commit()
    other_keys = {m["planned_meal"]["meal_key"] for m in _day(client, THU)["meals"]}
    assert other_keys.isdisjoint(meal_keys)  # a generated plan has meals of its own

    athlete.clock.advance(minutes=5)
    assert _activate(client, 1).status_code == 200
    assert _day(client, FRI)["session"]["plan_version"] == 1  # follows the newly active plan
    assert {m["planned_meal"]["meal_key"] for m in _day(client, THU)["meals"]} == meal_keys
    with Session(athlete.app.state.engine) as db:
        pending = db.scalars(
            select(Suggestion).where(Suggestion.planned_exercise_id == uuid.UUID(planned["id"]))
        ).one()
        assert pending.status == "rejected"
        past = db.get(TrainingSession, uuid.UUID(thursday["id"]))
        assert past is not None and past.status == "done"
    assert _logs(athlete) == logs_before


def test_a_plan_can_be_deleted_unless_it_is_current_and_it_disappears_everywhere(
    athlete: Api,  # noqa: F811
) -> None:
    client = athlete.client
    _edit(client)  # plan 1: v1, v2
    _new(client, "Second")  # plan 2: v3
    problem(_delete(client, 2), 409, "plan_is_current")
    assert [p["plan_no"] for p in _plans(client)] == [2, 1]

    assert _delete(client, 1).status_code == 204
    assert [p["plan_no"] for p in _plans(client)] == [2]
    assert {v["plan_no"] for v in _versions(client)} == {2}
    assert _versions(client, 1) == []
    for version in (1, 2):
        problem(client.get(f"{ME}/plan/versions/{version}"), 404, "not_found")
    problem(_delete(client, 1), 404, "plan_not_found")
    problem(_activate(client, 1), 404, "plan_not_found")
    problem(_delete(client, 99), 404, "plan_not_found")
    with Session(athlete.app.state.engine) as db:  # soft: nothing is dropped
        rows = db.scalars(select(Plan).order_by(Plan.version)).all()
        assert [(p.version, p.deleted_at is not None) for p in rows] == [
            (1, True),
            (2, True),
            (3, False),
        ]

    # numbers are never reused, not even after the highest plan is deleted
    assert _new(client, "Third")["plan_no"] == 3
    assert _activate(client, 2).status_code == 200
    assert _delete(client, 3).status_code == 204
    assert _new(client, "Fourth")["plan_no"] == 4
    assert [p["plan_no"] for p in _plans(client)] == [4, 2]
    assert [p["changes"] for p in _plans(client)] == [0, 0]


def test_deleting_a_plan_leaves_past_sessions_and_logs_alone(athlete: Api) -> None:  # noqa: F811
    client = athlete.client
    thursday = _day(client, THU)["session"]
    exercise = thursday["exercises"][0]["exercise"]["id"]
    logged = client.post(
        f"{BASE}/sessions/{thursday['id']}/sets",
        json={"exercise_id": exercise, "set_no": 1, "reps": 8, "weight_kg": 50},
    )
    assert logged.status_code in (200, 201), logged.text
    athlete.clock.advance(minutes=5)
    _new(client, "Second")
    before = _logs(athlete)
    assert _delete(client, 1).status_code == 204
    assert _logs(athlete) == before and len(before) == 1
    assert _day(client, THU)["session"]["id"] == thursday["id"]


def test_access_owner_linked_coach_and_strangers(athlete: Api) -> None:  # noqa: F811
    client = athlete.client
    ana = _plan(client)["athlete_id"]
    _new(client, "Second")
    _new(client, "Third")
    stranger = athlete.new_client()
    assert stranger.post(f"{BASE}/auth/signup", json=_signup("bob@x.test")).status_code == 201
    coach = athlete.new_client()
    resp = coach.post(f"{BASE}/auth/signup", json=_signup("cora@x.test", "coach"))
    assert resp.status_code == 201
    before = _rows(athlete)
    for other in (stranger, coach):
        problem(_activate(other, 1, ana), 403, "not_linked")
        problem(_delete(other, 1, ana), 403, "not_linked")
    problem(_activate(athlete.new_client(), 1, ana), 401, "not_authenticated")
    problem(_delete(athlete.new_client(), 1, ana), 401, "not_authenticated")
    assert _rows(athlete) == before
    assert _activate(client, 1, ana).status_code == 200  # by uuid works like "me"
    assert _delete(client, 2, ana).status_code == 204


def test_a_linked_coach_can_make_current_and_delete(w: World) -> None:  # noqa: F811
    with Session(w.api.app.state.engine) as db:
        run_seed(db)
    ana = w.athlete("Ana")
    assert ana.client.post(ONBOARD, json=onboarding()).status_code == 201
    _new(ana.client, "Second")
    assert _activate(w.cleo.client, 1, str(ana.id)).status_code == 200
    assert _plan(ana.client)["plan_no"] == 1
    assert _delete(w.cleo.client, 2, str(ana.id)).status_code == 204
    assert [p["plan_no"] for p in _plans(ana.client)] == [1]
    problem(_delete(w.cleo.client, 1, str(ana.id)), 409, "plan_is_current")
