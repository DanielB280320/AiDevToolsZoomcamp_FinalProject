"""#46 F16 coach profile, search and link requests against real Postgres: every endpoint for the
owner athlete, another athlete, the requested coach, another coach and a stranger (no session),
the link lifecycle, notifications, the entitlement hook and telemetry privacy."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import CoachLink, Entitlement, Notification
from tests.conftest import JsonLogs, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem, signup_body

P = "/api/v1/coach/profile"
S = "/api/v1/coaches/search"
L = "/api/v1/coach-links"


@dataclass
class Person:
    client: TestClient
    id: uuid.UUID
    email: str


def person(api: Api, email: str, role: str, name: str) -> Person:
    client = api.new_client()
    r = client.post(
        "/api/v1/auth/signup", json=signup_body(email=email, role=role, display_name=name)
    )
    assert r.status_code == 201, r.text
    return Person(client, uuid.UUID(r.json()["id"]), email)


@dataclass
class World:
    api: Api
    ana: Person  # owner athlete
    bob: Person  # other athlete
    cleo: Person  # requested coach
    dan: Person  # other coach
    stranger: TestClient  # no session


@pytest.fixture
def w(api: Api) -> World:
    return World(
        api,
        person(api, "ana@x.test", "athlete", "Ana Athlete"),
        person(api, "bob@x.test", "athlete", "Bob Athlete"),
        person(api, "cleo@x.test", "coach", "Cleo Coach"),
        person(api, "dan@x.test", "coach", "Dan Coach"),
        api.new_client(),
    )


def request(w: World, who: Person | None = None, coach: Person | None = None) -> dict[str, Any]:
    r = (who or w.ana).client.post(L, json={"coach_id": str((coach or w.cleo).id)})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def act(p: Person, link_id: str, verb: str) -> Any:
    return p.client.post(f"{L}/{link_id}/{verb}")


def notes(w: World, p: Person) -> list[Notification]:
    with Session(w.api.app.state.engine) as db:
        return list(
            db.scalars(
                select(Notification)
                .where(Notification.user_id == p.id)
                .order_by(Notification.created_at, Notification.id)
            )
        )


def set_status(w: World, link_id: str, status: str) -> None:
    with Session(w.api.app.state.engine) as db:
        link = db.get(CoachLink, uuid.UUID(link_id))
        assert link is not None
        link.status = status
        db.commit()


# ───────────── profile ─────────────


def test_profile_defaults_and_update(w: World) -> None:
    r = w.cleo.client.get(P)
    assert r.status_code == 200
    assert r.json() == {
        "user_id": str(w.cleo.id),
        "display_name": "Cleo Coach",
        "bio": "",
        "discoverable": True,
    }
    assert_matches_schema(r.json(), "CoachProfile")
    r = w.cleo.client.put(P, json={"bio": "Strength", "discoverable": False})
    assert r.status_code == 200 and r.json()["bio"] == "Strength"
    assert w.cleo.client.get(P).json()["discoverable"] is False
    # discoverable defaults to true when omitted
    assert w.cleo.client.put(P, json={"bio": "x"}).json()["discoverable"] is True


def test_profile_bio_limit(w: World) -> None:
    assert w.cleo.client.put(P, json={"bio": "b" * 500, "discoverable": True}).status_code == 200
    r = w.cleo.client.put(P, json={"bio": "b" * 501, "discoverable": True})
    problem(r, 422, "validation_error")


def test_profile_roles(w: World) -> None:
    for p in (w.ana, w.bob):
        problem(p.client.get(P), 403, "wrong_role")
        problem(p.client.put(P, json={"bio": "", "discoverable": True}), 403, "wrong_role")
    problem(w.stranger.get(P), 401, "not_authenticated")
    problem(w.stranger.put(P, json={"bio": "", "discoverable": True}), 401, "not_authenticated")


# ───────────── search ─────────────


def test_search_by_name_case_insensitive_and_shape(w: World) -> None:
    w.cleo.client.put(P, json={"bio": "Powerlifting", "discoverable": True})
    r = w.ana.client.get(S, params={"q": "cLEo"})
    assert r.status_code == 200
    assert r.json() == {
        "items": [{"id": str(w.cleo.id), "display_name": "Cleo Coach", "bio": "Powerlifting"}]
    }
    assert_matches_schema(r.json(), "CoachSearchResultList")
    assert "cleo@x.test" not in r.text
    names = [i["display_name"] for i in w.ana.client.get(S, params={"q": "Coach"}).json()["items"]]
    assert names == ["Cleo Coach", "Dan Coach"]


def test_search_exact_email_never_leaks_email(w: World) -> None:
    r = w.ana.client.get(S, params={"q": "Cleo@X.test"})
    assert [i["id"] for i in r.json()["items"]] == [str(w.cleo.id)]
    assert "x.test" not in r.text and set(r.json()["items"][0]) == {"id", "display_name", "bio"}
    # only an exact email, not a fragment of it
    assert w.ana.client.get(S, params={"q": "cleo@x"}).json()["items"] == []


def test_search_never_returns_athletes_or_hidden_coaches(w: World) -> None:
    assert w.ana.client.get(S, params={"q": "Athlete"}).json()["items"] == []
    assert w.ana.client.get(S, params={"q": "bob@x.test"}).json()["items"] == []
    w.dan.client.put(P, json={"bio": "", "discoverable": False})
    assert w.ana.client.get(S, params={"q": "Dan"}).json()["items"] == []
    assert w.ana.client.get(S, params={"q": "dan@x.test"}).json()["items"] == []


def test_search_query_length_and_wildcards(w: World) -> None:
    for q in ("", "ab", "  c "):
        problem(w.ana.client.get(S, params={"q": q}), 400, "bad_request")
    problem(w.ana.client.get(S), 400, "bad_request")
    assert w.ana.client.get(S, params={"q": "%%%"}).json()["items"] == []
    assert w.ana.client.get(S, params={"q": "C_e"}).json()["items"] == []


def test_search_max_20_results(w: World) -> None:
    for i in range(22):
        person(w.api, f"many{i}@x.test", "coach", f"Many Coach {i:02d}")
    assert len(w.ana.client.get(S, params={"q": "Many"}).json()["items"]) == 20


def test_search_roles(w: World) -> None:
    for p in (w.cleo, w.dan):
        problem(p.client.get(S, params={"q": "Cleo"}), 403, "wrong_role")
    problem(w.stranger.get(S, params={"q": "Cleo"}), 401, "not_authenticated")


# ───────────── request ─────────────


def test_request_creates_pending_link_and_notifies_coach(w: World) -> None:
    link = request(w)
    assert_matches_schema(link, "CoachLink")
    assert link["status"] == "pending" and link["source"] == "request"
    assert link["coach"]["id"] == str(w.cleo.id) and link["athlete"]["id"] == str(w.ana.id)
    (n,) = notes(w, w.cleo)
    assert n.type == "link_request_received"
    assert n.payload == {"link_id": link["id"], "actor": {"id": str(w.ana.id), "role": "athlete"}}
    assert notes(w, w.ana) == []


def test_request_conflicts(w: World) -> None:
    first = request(w)
    problem(w.ana.client.post(L, json={"coach_id": str(w.cleo.id)}), 409, "link_exists")
    problem(w.ana.client.post(L, json={"coach_id": str(w.dan.id)}), 409, "link_exists")
    assert act(w.cleo, first["id"], "approve").status_code == 200
    problem(w.ana.client.post(L, json={"coach_id": str(w.dan.id)}), 409, "link_exists")
    assert len(w.ana.client.get(L).json()["items"]) == 1
    assert len(notes(w, w.dan)) == 0


def test_request_unknown_hidden_or_non_coach_is_404(w: World) -> None:
    for target in (uuid.uuid4(), w.bob.id):
        problem(w.ana.client.post(L, json={"coach_id": str(target)}), 404, "not_found")
    w.dan.client.put(P, json={"bio": "", "discoverable": False})
    problem(w.ana.client.post(L, json={"coach_id": str(w.dan.id)}), 404, "not_found")
    assert w.ana.client.get(L).json()["items"] == []


def test_request_validation_and_roles(w: World) -> None:
    problem(w.ana.client.post(L, json={}), 422, "validation_error")
    problem(w.ana.client.post(L, json={"coach_id": "nope"}), 422, "validation_error")
    problem(
        w.ana.client.post(L, json={"coach_id": str(w.cleo.id), "x": 1}), 422, "validation_error"
    )
    for p in (w.cleo, w.dan):
        problem(p.client.post(L, json={"coach_id": str(w.cleo.id)}), 403, "wrong_role")
    problem(w.stranger.post(L, json={"coach_id": str(w.cleo.id)}), 401, "not_authenticated")


def test_declined_and_ended_links_do_not_block_a_new_request(w: World) -> None:
    a = request(w)
    assert act(w.cleo, a["id"], "decline").status_code == 200
    b = request(w, coach=w.dan)
    assert act(w.ana, b["id"], "end").status_code == 200
    c = request(w)
    assert act(w.cleo, c["id"], "approve").status_code == 200
    assert act(w.cleo, c["id"], "end").status_code == 200
    request(w)


def test_entitlement_false_blocks_request(w: World) -> None:
    with Session(w.api.app.state.engine) as db:
        db.add(Entitlement(user_id=w.ana.id, key="can_have_coach", value=False))
        db.commit()
    problem(w.ana.client.post(L, json={"coach_id": str(w.cleo.id)}), 403, "entitlement_required")
    # other users are unaffected; an explicit true row also passes
    request(w, who=w.bob)
    with Session(w.api.app.state.engine) as db:
        row = db.get(Entitlement, (w.ana.id, "can_have_coach"))
        assert row is not None
        row.value = True
        db.commit()
    request(w)


# ───────────── approve / decline ─────────────


@pytest.mark.parametrize(("verb", "status"), [("approve", "active"), ("decline", "declined")])
def test_requested_coach_decides(w: World, verb: str, status: str) -> None:
    link = request(w)
    r = act(w.cleo, link["id"], verb)
    assert r.status_code == 200 and r.json()["status"] == status
    assert_matches_schema(r.json(), "CoachLink")
    (n,) = notes(w, w.ana)
    assert n.type == {"approve": "link_request_approved", "decline": "link_request_declined"}[verb]
    assert n.payload == {"link_id": link["id"], "actor": {"id": str(w.cleo.id), "role": "coach"}}
    problem(act(w.cleo, link["id"], verb), 409, "link_not_pending")


@pytest.mark.parametrize("verb", ["approve", "decline"])
def test_decide_authorization(w: World, verb: str) -> None:
    link = request(w)
    problem(act(w.dan, link["id"], verb), 403, "forbidden")
    problem(act(w.ana, link["id"], verb), 403, "wrong_role")
    problem(act(w.bob, link["id"], verb), 403, "wrong_role")
    problem(w.stranger.post(f"{L}/{link['id']}/{verb}"), 401, "not_authenticated")
    problem(act(w.cleo, str(uuid.uuid4()), verb), 404, "not_found")
    problem(act(w.cleo, "nope", verb), 400, "bad_request")
    assert w.ana.client.get(L).json()["items"][0]["status"] == "pending"
    assert notes(w, w.ana) == []


@pytest.mark.parametrize("state", ["active", "declined", "ended"])
@pytest.mark.parametrize("verb", ["approve", "decline"])
def test_decide_needs_pending(w: World, verb: str, state: str) -> None:
    link = request(w)
    set_status(w, link["id"], state)
    problem(act(w.cleo, link["id"], verb), 409, "link_not_pending")


def test_approve_rejected_when_athlete_has_another_active_coach(w: World) -> None:
    link = request(w)
    with Session(w.api.app.state.engine) as db:
        db.add(
            CoachLink(
                id=uuid.uuid4(),
                coach_id=w.dan.id,
                athlete_id=w.ana.id,
                status="active",
                source="request",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        db.commit()
    problem(act(w.cleo, link["id"], "approve"), 409, "link_exists")
    assert act(w.cleo, link["id"], "decline").status_code == 200


# ───────────── end ─────────────


def test_athlete_withdraws_pending_and_coach_is_notified(w: World) -> None:
    link = request(w)
    r = act(w.ana, link["id"], "end")
    assert r.status_code == 200 and r.json()["status"] == "ended"
    cleo_notes = {n.type: n for n in notes(w, w.cleo)}
    assert set(cleo_notes) == {"link_request_received", "link_ended"}
    assert cleo_notes["link_ended"].payload == {
        "link_id": link["id"],
        "actor": {"id": str(w.ana.id), "role": "athlete"},
    }
    problem(act(w.cleo, link["id"], "approve"), 409, "link_not_pending")


@pytest.mark.parametrize("who", ["ana", "cleo"])
def test_either_side_ends_active_link(w: World, who: str) -> None:
    link = request(w)
    act(w.cleo, link["id"], "approve")
    ender, other = (w.ana, w.cleo) if who == "ana" else (w.cleo, w.ana)
    r = act(ender, link["id"], "end")
    assert r.status_code == 200 and r.json()["status"] == "ended"
    assert_matches_schema(r.json(), "CoachLink")
    assert "link_ended" in {n.type for n in notes(w, other)}
    assert "link_ended" not in {n.type for n in notes(w, ender)}
    for p in (w.ana, w.cleo):
        assert p.client.get(L, params={"status": "active"}).json()["items"] == []
        assert [
            i["status"] for i in p.client.get(L, params={"status": "ended"}).json()["items"]
        ] == ["ended"]
    assert w.ana.client.get("/api/v1/me").json()["active_coach"] is None
    problem(act(ender, link["id"], "end"), 409, "link_not_pending")


@pytest.mark.parametrize("state", ["declined", "ended"])
def test_end_needs_pending_or_active(w: World, state: str) -> None:
    link = request(w)
    set_status(w, link["id"], state)
    problem(act(w.ana, link["id"], "end"), 409, "link_not_pending")


def test_end_authorization(w: World) -> None:
    link = request(w)
    act(w.cleo, link["id"], "approve")
    problem(act(w.bob, link["id"], "end"), 403, "forbidden")
    problem(act(w.dan, link["id"], "end"), 403, "forbidden")
    problem(w.stranger.post(f"{L}/{link['id']}/end"), 401, "not_authenticated")
    problem(act(w.ana, str(uuid.uuid4()), "end"), 404, "not_found")
    assert w.cleo.client.get(L, params={"status": "active"}).json()["items"][0]["id"] == link["id"]


# ───────────── list and /me ─────────────


def test_list_scopes_order_and_filter(w: World) -> None:
    first = request(w)
    act(w.cleo, first["id"], "decline")
    w.api.clock.advance(seconds=60)
    second = request(w)
    request(w, who=w.bob)
    ana = w.ana.client.get(L).json()
    assert [i["id"] for i in ana["items"]] == [second["id"], first["id"]]
    assert_matches_schema(ana, "CoachLinkList")
    assert [i["id"] for i in w.ana.client.get(L, params={"status": "pending"}).json()["items"]] == [
        second["id"]
    ]
    assert len(w.cleo.client.get(L, params={"status": "pending"}).json()["items"]) == 2
    assert len(w.bob.client.get(L).json()["items"]) == 1
    assert w.dan.client.get(L).json()["items"] == []
    problem(w.ana.client.get(L, params={"status": "bogus"}), 400, "bad_request")
    problem(w.stranger.get(L), 401, "not_authenticated")


def test_me_shows_pending_and_active_coach(w: World) -> None:
    link = request(w)
    me = w.ana.client.get("/api/v1/me").json()
    assert me["pending_coach_link_id"] == link["id"] and me["active_coach"] is None
    act(w.cleo, link["id"], "approve")
    me = w.ana.client.get("/api/v1/me").json()
    assert me["pending_coach_link_id"] is None
    assert me["active_coach"] == {
        "id": str(w.cleo.id),
        "display_name": "Cleo Coach",
        "role": "coach",
    }


# ───────────── telemetry ─────────────


def test_no_names_emails_or_bio_in_telemetry(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, exporter, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    with TestClient(app) as a, TestClient(app) as c:
        ids = {}
        for client, email, role, name in (
            (a, "zed.athlete@x.test", "athlete", "Zedathletename"),
            (c, "yan.coach@x.test", "coach", "Yancoachname"),
        ):
            r = client.post(
                "/api/v1/auth/signup",
                json=signup_body(email=email, role=role, display_name=name),
            )
            ids[role] = r.json()["id"]
        assert c.put(P, json={"bio": "Zebiosentinel", "discoverable": True}).status_code == 200
        assert a.get(S, params={"q": "yan.coach@x.test"}).status_code == 200
        link = a.post(L, json={"coach_id": ids["coach"]}).json()
        assert c.post(f"{L}/{link['id']}/approve").status_code == 200
        assert a.post(f"{L}/{link['id']}/end").status_code == 200
    blob = (
        json_logs.text
        + repr([(dict(s.attributes or {}), s.name) for s in exporter.get_finished_spans()])
        + repr(reader.get_metrics_data())
    )
    for secret in ("Zedathletename", "Yancoachname", "zed.athlete", "yan.coach", "Zebiosentinel"):
        assert secret not in blob, secret
