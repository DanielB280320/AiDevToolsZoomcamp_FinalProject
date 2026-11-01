"""#47 F16 authorization matrix, generated from `x-fitwise-access` in `openapi.yaml`.

Every path+method of the contract must declare a known access value (a new endpoint cannot ship
uncovered). For each `owner` / `owner-or-coach` operation the owner, a linked coach, coaches with
no / pending / declined / ended link and a stranger athlete call it against real rows in Postgres
(plan, session, set log, suggestion, meal log, activity); the access query is never mocked. A
denied call must also leave the database byte-for-byte unchanged.

Operations that do not exist yet sit in `NOT_YET_IMPLEMENTED`; the owning issue removes them.
"""

import datetime as dt
import hashlib
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import CoachLink, Exercise, Food, PlanChange
from app.models.base import Base
from app.seed import run_seed
from tests.conftest import make_settings
from tests.contract import contract
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, signup_body
from tests.integration.conftest import alembic_config
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_plan_editor import _meals_body, _training_body

API = "/api/v1"
METHODS = ("get", "post", "put", "patch", "delete")
KNOWN_ACCESS = {"public", "authenticated", "athlete", "coach", "owner", "owner-or-coach", "author"}
ATHLETE_SCOPED = {"owner", "owner-or-coach"}

# Not implemented yet. #50 deletes its entries; the test
# `test_not_yet_implemented_entries_are_really_missing` fails when an entry is implemented.
NOT_YET_IMPLEMENTED: set[tuple[str, str]] = {
    ("POST", "/me/delete"),  # #50
    ("GET", "/me/export"),  # #50
}


# ───────────── the contract ─────────────


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    access: str

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


def enumerate_operations(spec: dict[str, Any]) -> list[Operation]:
    """Every path+method of `spec`; fails on a missing or unknown `x-fitwise-access`."""
    found: list[Operation] = []
    for path, item in spec["paths"].items():
        for method in METHODS:
            if method not in item:
                continue
            access = item[method].get("x-fitwise-access")
            where = f"{method.upper()} {path}"
            assert access is not None, f"{where} has no x-fitwise-access"
            assert access in KNOWN_ACCESS, f"{where} has unknown x-fitwise-access {access!r}"
            found.append(Operation(method.upper(), path, access))
    return found


OPERATIONS = enumerate_operations(contract())


def implemented(op: Operation) -> bool:
    return (op.method, op.path) not in NOT_YET_IMPLEMENTED


def operations(*accesses: str) -> list[Operation]:
    return [o for o in OPERATIONS if o.access in accesses and implemented(o)]


def test_every_operation_declares_a_known_access_value() -> None:
    assert len(OPERATIONS) > 40  # the whole contract was enumerated


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({}, "has no x-fitwise-access"),
        ({"x-fitwise-access": "everyone"}, "unknown x-fitwise-access"),
    ],
)
def test_a_missing_or_unknown_access_value_fails_the_enumeration(
    patch: dict[str, str], message: str
) -> None:
    spec = {"paths": {"/new": {"get": patch, "parameters": []}}}
    with pytest.raises(AssertionError, match=message):
        enumerate_operations(spec)


# ───────────── the world ─────────────


@dataclass
class Person:
    client: TestClient
    id: uuid.UUID


@dataclass
class World:
    app: FastAPI
    engine: Engine
    ana: Person  # the owner athlete (onboarded)
    bob: Person  # a stranger athlete
    cleo: Person  # coach with an active link to ana (and to nobody else)
    dan: Person  # coach with no link
    eve: Person  # coach with a pending request
    fay: Person  # coach whose request was declined
    gus: Person  # coach whose link ended
    anonymous: TestClient
    food_id: str = ""
    exercise_id: str = ""
    week: int = field(default=0)

    def next_monday(self) -> dt.date:
        """A fresh Monday (the plan trains on Mondays), so every session is a new row."""
        self.week += 1
        return dt.date(2026, 11, 2) + dt.timedelta(weeks=self.week)


def _person(app: FastAPI, email: str, role: str) -> Person:
    client = TestClient(app)
    client.__enter__()
    r = client.post(
        f"{API}/auth/signup", json=signup_body(email=email, role=role, display_name=email[:3])
    )
    assert r.status_code == 201, r.text
    return Person(client, uuid.UUID(r.json()["id"]))


def _link(w_ana: Person, coach: Person) -> str:
    r = w_ana.client.post(f"{API}/coach-links", json={"coach_id": str(coach.id)})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


@pytest.fixture(scope="module")
def world(admin_url: str) -> Iterator[World]:
    name = f"fitwise_it_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    command.upgrade(alembic_config(url), "head")
    app = create_app(make_settings(url))
    app.state.clock = FakeClock(NOW)
    people: list[Person] = []
    try:
        with Session(app.state.engine) as db:
            run_seed(db)
        ana = _person(app, "ana@x.test", "athlete")
        bob = _person(app, "bob@x.test", "athlete")
        cleo, dan, eve, fay, gus = (
            _person(app, f"{n}@x.test", "coach") for n in ("cleo", "dan", "eve", "fay", "gus")
        )
        people = [ana, bob, cleo, dan, eve, fay, gus]
        r = ana.client.post(ONBOARD, json=onboarding())
        assert r.status_code == 201, r.text
        # One open link per athlete at a time, so the states are walked through in order:
        # ended (gus), declined (fay), then active (cleo).
        link = _link(ana, gus)
        assert gus.client.post(f"{API}/coach-links/{link}/approve").status_code == 200
        assert ana.client.post(f"{API}/coach-links/{link}/end").status_code == 200
        link = _link(ana, fay)
        assert fay.client.post(f"{API}/coach-links/{link}/decline").status_code == 200
        link = _link(ana, cleo)
        assert cleo.client.post(f"{API}/coach-links/{link}/approve").status_code == 200
        with Session(app.state.engine) as db:  # the API allows no pending request next to an
            db.add(  # active link, the database does: a row is enough to prove it grants nothing
                CoachLink(
                    coach_id=eve.id,
                    athlete_id=ana.id,
                    status="pending",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            db.commit()
        with Session(app.state.engine) as db:
            food_id = str(db.scalars(select(Food.id).limit(1)).one())
            exercise_id = str(
                db.scalars(
                    select(Exercise.id)
                    .where(Exercise.owner_id.is_(None), Exercise.type == "timed")
                    .limit(1)
                ).one()
            )
        yield World(
            app, app.state.engine, ana, bob, cleo, dan, eve, fay, gus,
            TestClient(app), food_id, exercise_id,
        )  # fmt: skip
    finally:
        for person in people:
            person.client.__exit__(None, None, None)
        app.state.engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def fingerprint(engine: Engine) -> str:
    """A hash of every row of every table: equal before and after means nothing changed."""
    digest = hashlib.sha256()
    with Session(engine) as db:
        for table in Base.metadata.sorted_tables:
            rows = db.execute(select(table)).all()
            digest.update(table.name.encode())
            for row in sorted(repr(tuple(r)) for r in rows):
                digest.update(row.encode())
    return digest.hexdigest()


# ───────────── fresh resources (created as the owner through the API) ─────────────


def new_session(w: World) -> dict[str, Any]:
    r = w.ana.client.get(f"{API}/athletes/me/days/{w.next_monday()}")
    assert r.status_code == 200, r.text
    session: dict[str, Any] = r.json()["session"]
    assert session is not None, "the generated plan trains on Mondays"
    return session


def set_body(exercise: dict[str, Any], set_no: int = 1) -> dict[str, Any]:
    kind = exercise["exercise"]["type"]
    values: dict[str, Any] = (
        {"seconds": 30} if kind == "timed" else {"reps": 8, "weight_kg": 20} if kind == "strength"
        else {"reps": 8}
    )  # fmt: skip
    return {
        "exercise_id": exercise["exercise"]["id"],
        "planned_exercise_id": exercise["planned_exercise_id"],
        "set_no": set_no,
        **values,
    }


def new_set_log(w: World) -> tuple[str, str]:
    session = new_session(w)
    r = w.ana.client.post(
        f"{API}/sessions/{session['id']}/sets", json=set_body(session["exercises"][0])
    )
    assert r.status_code == 201, r.text
    return session["id"], r.json()["id"]


def new_suggestion(w: World) -> str:
    session = new_session(w)
    for n, exercise in enumerate(session["exercises"], start=1):
        r = w.ana.client.post(f"{API}/sessions/{session['id']}/sets", json=set_body(exercise, n))
        assert r.status_code == 201, r.text
    r = w.ana.client.post(f"{API}/sessions/{session['id']}/finish")
    assert r.status_code == 200, r.text
    created = r.json()["suggestions"]
    assert created, "finishing a performed session creates a suggestion"
    return str(created[0]["id"])


def new_meal_log(w: World) -> str:
    r = w.ana.client.post(
        f"{API}/athletes/me/meal-logs",
        json={
            "date": "2026-10-22",
            "planned_meal_id": None,
            "status": "extra",
            "slot": "snack",
            "items": [{"food_id": w.food_id, "grams": 100}],
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["meal_log"]["id"])


def activity_body(w: World) -> dict[str, Any]:
    return {"date": "2026-10-22", "exercise_id": w.exercise_id, "minutes": 10}


def new_activity(w: World) -> str:
    r = w.ana.client.post(f"{API}/athletes/me/activities", json=activity_body(w))
    assert r.status_code == 201, r.text
    return str(r.json()["activity"]["id"])


def plan(w: World) -> dict[str, Any]:
    body: dict[str, Any] = w.ana.client.get(f"{API}/athletes/me/plan").json()
    return body


@dataclass
class Request:
    """What to send for an operation, with fresh rows for its path parameters."""

    values: dict[str, str] = field(default_factory=dict)
    json: Any = None
    params: dict[str, Any] | None = None


Builder = Callable[[World], Request]

RANGE = {"from": "2026-10-19", "to": "2026-10-25"}
PROFILE = onboarding()["profile"]


def _sid(w: World) -> Request:
    return Request({"session_id": new_session(w)["id"]})


def _delete_set(w: World) -> Request:
    sid, log_id = new_set_log(w)
    return Request({"session_id": sid, "set_log_id": log_id})


def _log_set(w: World) -> Request:
    session = new_session(w)
    return Request({"session_id": session["id"]}, json=set_body(session["exercises"][0]))


def _move(w: World) -> Request:
    session = new_session(w)
    target = dt.date.fromisoformat(session["date"]) + dt.timedelta(days=1)
    return Request({"session_id": session["id"]}, json={"date": target.isoformat()})


def _session_chart(w: World) -> Request:
    return Request({"session_id": new_session(w)["id"]})


BUILDERS: dict[str, Builder] = {
    "POST /athletes/{athlete_id}/onboarding": lambda w: Request(json=onboarding()),
    "GET /athletes/{athlete_id}/profile": lambda w: Request(),
    "PUT /athletes/{athlete_id}/profile": lambda w: Request(json=PROFILE),
    "GET /athletes/{athlete_id}/targets": lambda w: Request(),
    "GET /athletes/{athlete_id}/body-metrics": lambda w: Request(),
    "POST /athletes/{athlete_id}/body-metrics": lambda w: Request(
        json={"date": "2026-10-20", "weight_kg": 72.0}
    ),
    "GET /athletes/{athlete_id}/plan": lambda w: Request(),
    "PUT /athletes/{athlete_id}/plan/training": lambda w: Request(json=_training_body(plan(w))),
    "PUT /athletes/{athlete_id}/plan/meals": lambda w: Request(json=_meals_body(plan(w))),
    "POST /athletes/{athlete_id}/plan/regenerate": lambda w: Request(json={"scope": "training"}),
    "GET /athletes/{athlete_id}/plan/versions": lambda w: Request(),
    "GET /athletes/{athlete_id}/plan/versions/{version}": lambda w: Request({"version": "1"}),
    "GET /athletes/{athlete_id}/days/{date}": lambda w: Request({"date": "2026-10-22"}),
    "GET /athletes/{athlete_id}/calendar": lambda w: Request(params=RANGE),
    "GET /sessions/{session_id}": _sid,
    "POST /sessions/{session_id}/move": _move,
    "POST /sessions/{session_id}/sets": _log_set,
    "DELETE /sessions/{session_id}/sets/{set_log_id}": _delete_set,
    "POST /sessions/{session_id}/finish": lambda w: Request({"session_id": new_set_log(w)[0]}),
    "POST /athletes/{athlete_id}/meal-logs": lambda w: Request(
        json={
            "date": "2026-10-22",
            "planned_meal_id": None,
            "status": "extra",
            "slot": "snack",
            "items": [{"food_id": w.food_id, "grams": 50}],
        }
    ),
    "DELETE /athletes/{athlete_id}/meal-logs/{meal_log_id}": lambda w: Request(
        {"meal_log_id": new_meal_log(w)}
    ),
    "POST /athletes/{athlete_id}/activities": lambda w: Request(json=activity_body(w)),
    "DELETE /athletes/{athlete_id}/activities/{activity_id}": lambda w: Request(
        {"activity_id": new_activity(w)}
    ),
    "GET /athletes/{athlete_id}/notes": lambda w: Request(),
    "GET /athletes/{athlete_id}/suggestions": lambda w: Request(),
    "POST /suggestions/{suggestion_id}/accept": lambda w: Request(
        {"suggestion_id": new_suggestion(w)}
    ),
    "POST /suggestions/{suggestion_id}/reject": lambda w: Request(
        {"suggestion_id": new_suggestion(w)}
    ),
    "GET /athletes/{athlete_id}/charts/session/{session_id}": _session_chart,
    "GET /athletes/{athlete_id}/charts/exercise/{exercise_id}": lambda w: Request(
        {"exercise_id": w.exercise_id}
    ),
    "GET /athletes/{athlete_id}/charts/adherence": lambda w: Request(params=RANGE),
    "GET /athletes/{athlete_id}/charts/weekly-summary": lambda w: Request(),
    "GET /athletes/{athlete_id}/charts/body": lambda w: Request(),
}


def send(w: World, client: TestClient, op: Operation, req: Request, athlete: str) -> Any:
    values = {"athlete_id": athlete, **req.values}
    url = API + op.path.format(**values)
    return client.request(op.method, url, json=req.json, params=req.params)


def test_every_athlete_scoped_operation_has_a_builder() -> None:
    wanted = {o.id for o in operations(*ATHLETE_SCOPED)}
    assert wanted == set(BUILDERS), wanted ^ set(BUILDERS)


# ───────────── owner and coach matrix ─────────────

ACTORS = [
    "owner",
    "linked_coach",
    "unlinked_coach",
    "pending_coach",
    "declined_coach",
    "ended_coach",
    "stranger",
]
DENIED_NOT_LINKED = {
    "unlinked_coach", "pending_coach", "declined_coach", "ended_coach", "stranger"
}  # fmt: skip


def actor_client(w: World, actor: str) -> TestClient:
    return {
        "owner": w.ana,
        "linked_coach": w.cleo,
        "unlinked_coach": w.dan,
        "pending_coach": w.eve,
        "declined_coach": w.fay,
        "ended_coach": w.gus,
        "stranger": w.bob,
    }[actor].client


def _shape(r: Any) -> dict[str, Any]:
    return {k: v for k, v in r.json().items() if k != "request_id"}


def assert_not_linked(r: Any) -> None:
    assert r.status_code == 403, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "not_linked", r.text


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("op", operations(*ATHLETE_SCOPED), ids=lambda o: o.id)
def test_matrix(world: World, op: Operation, actor: str) -> None:
    req = BUILDERS[op.id](world)
    client = actor_client(world, actor)
    before = fingerprint(world.engine)
    # Onboarding twice is a 409 for the owner: it is the owner's "normal" answer here.
    r = send(world, client, op, req, str(world.ana.id))
    if actor == "owner" or (actor == "linked_coach" and op.access == "owner-or-coach"):
        ok = (409,) if op.path.endswith("/onboarding") and actor == "owner" else range(200, 300)
        assert r.status_code in ok, r.text
    elif actor == "linked_coach":
        assert r.status_code == 403, r.text
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.json()["code"] == "wrong_role"
        assert fingerprint(world.engine) == before, "a denied call changed the database"
    else:
        assert actor in DENIED_NOT_LINKED
        assert_not_linked(r)
        assert fingerprint(world.engine) == before, "a denied call changed the database"


@pytest.mark.parametrize(
    "op",
    [o for o in operations(*ATHLETE_SCOPED) if not o.path.endswith("/onboarding")],
    ids=lambda o: o.id,
)
def test_owner_by_me_and_by_uuid_both_work(world: World, op: Operation) -> None:
    # Onboarding is once only: its 409 for the owner is covered by the matrix row.
    for athlete in ("me", str(world.ana.id)):
        r = send(world, world.ana.client, op, BUILDERS[op.id](world), athlete)
        assert 200 <= r.status_code < 300, (athlete, r.text)


athlete_paths = [o for o in operations(*ATHLETE_SCOPED) if "{athlete_id}" in o.path]


@pytest.mark.parametrize("op", athlete_paths, ids=lambda o: o.id)
def test_a_coach_calling_me_is_forbidden(world: World, op: Operation) -> None:
    req = BUILDERS[op.id](world)
    before = fingerprint(world.engine)
    r = send(world, world.cleo.client, op, req, "me")
    assert r.status_code == 403, r.text
    assert fingerprint(world.engine) == before


@pytest.mark.parametrize("op", athlete_paths, ids=lambda o: o.id)
def test_a_coach_linked_to_a_is_not_linked_to_b(world: World, op: Operation) -> None:
    req = BUILDERS[op.id](world)
    before = fingerprint(world.engine)
    r = send(world, world.cleo.client, op, req, str(world.bob.id))
    assert_not_linked(r)
    assert fingerprint(world.engine) == before


@pytest.mark.parametrize("op", athlete_paths, ids=lambda o: o.id)
def test_unknown_athlete_ids_look_like_not_linked_and_malformed_is_400(
    world: World, op: Operation
) -> None:
    req = BUILDERS[op.id](world)
    known = send(world, world.bob.client, op, req, str(world.ana.id))
    for who in (world.ana, world.cleo, world.bob):
        unknown = send(world, who.client, op, req, str(uuid.uuid4()))
        assert_not_linked(unknown)
        assert _shape(unknown) == _shape(known)  # D41: same body shape, nothing to enumerate
        bad = send(world, who.client, op, req, "not-a-uuid")
        assert bad.status_code == 400, bad.text
        assert bad.json()["code"] == "bad_request"


session_ops = [o for o in operations(*ATHLETE_SCOPED) if o.path.startswith("/sessions/")]


@pytest.mark.parametrize("op", session_ops, ids=lambda o: o.id)
def test_an_unknown_session_is_403_not_404(world: World, op: Operation) -> None:
    req = BUILDERS[op.id](world)
    req.values["session_id"] = str(uuid.uuid4())
    for who in (world.ana, world.cleo, world.bob):
        assert_not_linked(send(world, who.client, op, req, "me"))


@pytest.mark.parametrize("verb", ["accept", "reject"])
def test_suggestions_by_id_unknown_or_foreign_are_403_not_linked(world: World, verb: str) -> None:
    path = f"{API}/suggestions/{{}}/{verb}"
    mine = new_suggestion(world)
    for who in (world.ana, world.cleo):
        assert_not_linked(who.client.post(path.format(uuid.uuid4())))
    # Another athlete's suggestion (ana's) for a stranger and for an unlinked coach.
    for who in (world.bob, world.dan, world.gus):
        before = fingerprint(world.engine)
        assert_not_linked(who.client.post(path.format(mine)))
        assert fingerprint(world.engine) == before


def test_ending_a_link_takes_effect_on_the_very_next_request(world: World) -> None:
    ivy = _person(world.app, "ivy@x.test", "coach")
    try:
        # bob, not ana: an athlete has one open link at a time and ana's is cleo's.
        link = _link(world.bob, ivy)
        assert ivy.client.post(f"{API}/coach-links/{link}/approve").status_code == 200
        url = f"{API}/athletes/{world.bob.id}/profile"
        assert ivy.client.get(url).status_code == 404  # allowed: bob has not onboarded
        assert world.bob.client.post(f"{API}/coach-links/{link}/end").status_code == 200
        assert_not_linked(ivy.client.get(url))
    finally:
        ivy.client.__exit__(None, None, None)


def test_a_coach_plan_edit_stores_author_role_coach(world: World) -> None:
    body = _training_body(plan(world))
    r = world.cleo.client.put(f"{API}/athletes/{world.ana.id}/plan/training", json=body)
    assert r.status_code == 200, r.text
    with Session(world.engine) as db:
        change = db.scalars(select(PlanChange).where(PlanChange.author_id == world.cleo.id)).first()
        assert change is not None
        assert change.author_role == "coach"
        assert change.author_id == world.cleo.id


# ───────────── authentication and roles ─────────────


def filled(op: Operation) -> str:
    random_ids = {
        k: str(uuid.uuid4())
        for k in (
            "athlete_id", "session_id", "set_log_id", "meal_log_id", "activity_id",
            "suggestion_id", "exercise_id", "link_id", "notification_id", "note_id",
        )
    }  # fmt: skip
    return API + op.path.format_map(random_ids | {"version": "1", "date": "2026-10-22"})


@pytest.mark.parametrize(
    "op", [o for o in OPERATIONS if o.access != "public" and implemented(o)], ids=lambda o: o.id
)
def test_without_a_session_every_non_public_operation_is_401(world: World, op: Operation) -> None:
    r = world.anonymous.request(op.method, filled(op))
    assert r.status_code == 401, r.text
    assert r.json()["code"] == "not_authenticated"


@pytest.mark.parametrize("op", operations("coach"), ids=lambda o: o.id)
def test_coach_operations_are_wrong_role_for_athletes(world: World, op: Operation) -> None:
    r = world.ana.client.request(op.method, filled(op), json={})
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "wrong_role"


@pytest.mark.parametrize("op", operations("athlete"), ids=lambda o: o.id)
def test_athlete_operations_are_wrong_role_for_coaches(world: World, op: Operation) -> None:
    r = world.cleo.client.request(op.method, filled(op), json={})
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "wrong_role"


# ───────────── operations that do not exist yet ─────────────


def test_not_yet_implemented_entries_are_really_missing(world: World) -> None:
    routes = {
        (method.upper(), path.removeprefix(API))
        for path, item in world.app.openapi()["paths"].items()
        for method in item
    }
    for entry in NOT_YET_IMPLEMENTED:
        assert entry in {(o.method, o.path) for o in OPERATIONS}, f"{entry} is not in the contract"
        assert entry not in routes, f"{entry} is implemented: remove it from NOT_YET_IMPLEMENTED"
    for op in OPERATIONS:
        if implemented(op):
            assert (op.method, op.path) in routes, f"{op.id} is in the contract but not served"
