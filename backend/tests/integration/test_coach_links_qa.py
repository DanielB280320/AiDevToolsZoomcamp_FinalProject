"""QA additions for #46 (F16 linking, D81): the link notifications as the recipient reads them
through `GET /notifications` match the contract (`NotificationActor` = id + role only), and the
partial unique indexes enforce one active and one pending link per athlete at the database level
(the race guard behind `409 link_exists`)."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CoachLink
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api
from tests.integration.test_coach_links import World, act, person, request

N = "/api/v1/notifications"


@pytest.fixture(name="w")
def world(api: Api) -> World:
    return World(
        api,
        person(api, "ana@x.test", "athlete", "Ana Athlete"),
        person(api, "bob@x.test", "athlete", "Bob Athlete"),
        person(api, "cleo@x.test", "coach", "Cleo Coach"),
        person(api, "dan@x.test", "coach", "Dan Coach"),
        api.new_client(),
    )


def _link_items(client: TestClient, link_id: str) -> list[dict[str, Any]]:
    page: dict[str, Any] = client.get(N).json()
    assert_matches_schema(page, "NotificationPage")
    return [i for i in page["items"] if i["payload"].get("link_id") == link_id]


def test_link_notifications_via_api_carry_only_link_id_and_actor_id_role(w: World) -> None:
    link = request(w)
    assert act(w.cleo, link["id"], "approve").status_code == 200
    assert act(w.cleo, link["id"], "end").status_code == 200
    coach_items = _link_items(w.cleo.client, link["id"])
    athlete_items = _link_items(w.ana.client, link["id"])
    assert {i["type"] for i in coach_items} == {"link_request_received"}
    assert {i["type"] for i in athlete_items} == {"link_request_approved", "link_ended"}
    for item, actor in [(i, w.ana) for i in coach_items] + [(i, w.cleo) for i in athlete_items]:
        assert set(item["payload"]) == {"link_id", "actor"}
        assert set(item["payload"]["actor"]) == {"id", "role"}
        assert item["payload"]["actor"]["id"] == str(actor.id)
        assert_matches_schema(item["payload"], "NotificationPayload")
        blob = repr(item)
        for secret in ("Ana Athlete", "Cleo Coach", "ana@x.test", "cleo@x.test"):
            assert secret not in blob
    # Other athlete and other coach see none of these notifications.
    assert _link_items(w.bob.client, link["id"]) == []
    assert _link_items(w.dan.client, link["id"]) == []


@pytest.mark.parametrize("status", ["active", "pending"])
def test_partial_unique_index_allows_one_active_and_one_pending_per_athlete(
    api: Api, w: World, status: str
) -> None:
    def row(coach_id: uuid.UUID, st: str) -> CoachLink:
        return CoachLink(
            id=uuid.uuid4(),
            coach_id=coach_id,
            athlete_id=w.ana.id,
            status=st,
            source="request",
            created_at=NOW,
            updated_at=NOW,
        )

    with Session(api.app.state.engine) as db:
        db.add(row(w.cleo.id, status))
        db.commit()
        # Ended/declined history never collides.
        db.add_all([row(w.dan.id, "ended"), row(w.dan.id, "declined"), row(w.cleo.id, "ended")])
        db.commit()
        db.add(row(w.dan.id, status))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        count = db.execute(
            text("SELECT count(*) FROM coach_link WHERE athlete_id = :a AND status = :s"),
            {"a": w.ana.id, "s": status},
        ).scalar_one()
        assert count == 1


def test_unknown_link_is_404_for_every_transition(w: World) -> None:
    unknown = str(uuid.uuid4())
    for p, verb in ((w.cleo, "approve"), (w.cleo, "decline"), (w.ana, "end"), (w.cleo, "end")):
        r = act(p, unknown, verb)
        assert r.status_code == 404, (verb, r.text)
        assert r.json()["code"] == "not_found"
