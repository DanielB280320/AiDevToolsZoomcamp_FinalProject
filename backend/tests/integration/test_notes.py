"""#49 F16 coach notes against real Postgres: create, list, day view, edit, delete, author access,
the `coach_note` notification, notes outliving the link (D84), cascade and telemetry privacy."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import CoachNote, Notification
from tests.conftest import Captured, JsonLogs, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, problem, signup_body
from tests.integration.test_authorization_matrix import (
    API,
    OPERATIONS,
    World,
    _link,
    _person,
    new_session,
    world,  # noqa: F401  (module fixture reused)
)
from tests.integration.test_onboarding import ONBOARD, onboarding

TEXT = "Keep your elbows tucked on the bench"


def notes_url(athlete: object) -> str:
    return f"{API}/athletes/{athlete}/notes"


def day_note(date: str = "2026-10-22", text_: str = TEXT) -> dict[str, Any]:
    return {"scope": "day", "date": date, "text": text_}


def create(w: World, body: dict[str, Any], who: str = "cleo") -> Any:
    return getattr(w, who).client.post(notes_url(w.ana.id), json=body)


# ───────────── create ─────────────


def test_a_linked_coach_creates_a_note_of_each_scope(world: World) -> None:  # noqa: F811
    session = new_session(world)
    exercise = session["exercises"][0]["exercise"]
    bodies = [
        day_note(),
        {"scope": "session", "session_id": session["id"], "text": "Good session"},
        {"scope": "exercise", "exercise_id": exercise["id"], "text": "Slow the negative"},
        {
            "scope": "exercise",
            "exercise_id": exercise["id"],
            "session_id": session["id"],
            "text": "Today only",
        },
    ]
    for body in bodies:
        r = create(world, body)
        assert r.status_code == 201, r.text
        assert_matches_schema(r.json(), "Note")
        note = r.json()
        assert note["scope"] == body["scope"]
        assert note["text"] == body["text"]
        assert note["author"]["id"] == str(world.cleo.id)
        assert note["athlete_id"] == str(world.ana.id)


@pytest.mark.parametrize(
    "body",
    [
        {"scope": "day", "text": "x"},
        {"scope": "session", "date": "2026-10-22", "text": "x"},
        {"scope": "exercise", "session_id": str(uuid.uuid4()), "text": "x"},
        {"scope": "day", "date": "2026-10-22", "text": ""},
        {"scope": "day", "date": "2026-10-22", "text": "x" * 2001},
        {"scope": "day", "date": "2026-10-22"},
        {"scope": "week", "date": "2026-10-22", "text": "x"},
        {"scope": "day", "date": "2026-10-22", "text": "x", "extra": 1},
    ],
)
def test_invalid_bodies_are_422(world: World, body: dict[str, Any]) -> None:  # noqa: F811
    problem(create(world, body), 422, "validation_error")


def test_text_of_exactly_1_and_2000_characters_is_accepted(world: World) -> None:  # noqa: F811
    assert create(world, day_note(text_="x")).status_code == 201
    assert create(world, day_note(text_="x" * 2000)).status_code == 201


def test_unknown_or_foreign_targets_are_404(world: World) -> None:  # noqa: F811
    bobs = world.bob.client.get(f"{API}/athletes/me/days/today")
    assert bobs.status_code == 200
    with Session(world.engine) as db:
        foreign_exercise = db.execute(
            text("select id from exercise where owner_id is null limit 1")
        ).scalar_one()
    unknown = str(uuid.uuid4())
    for body in (
        {"scope": "session", "session_id": unknown, "text": "x"},
        {"scope": "exercise", "exercise_id": unknown, "text": "x"},
        {
            "scope": "exercise",
            "exercise_id": str(foreign_exercise),
            "session_id": unknown,
            "text": "x",
        },
    ):
        problem(create(world, body), 404, "not_found")


def test_a_session_of_another_athlete_is_404(world: World) -> None:  # noqa: F811
    hal = _person(world.app, "hal2@x.test", "athlete")
    try:
        assert hal.client.post(ONBOARD, json=onboarding()).status_code == 201
        day = hal.client.get(f"{API}/athletes/me/days/{world.next_monday()}").json()
        assert day["session"] is not None
        body = {"scope": "session", "session_id": day["session"]["id"], "text": "x"}
        problem(create(world, body), 404, "not_found")
    finally:
        hal.client.__exit__(None, None, None)


def test_a_custom_exercise_of_another_user_is_404(world: World) -> None:  # noqa: F811
    r = world.bob.client.post(
        f"{API}/exercises",
        json={
            "name": "Bob special",
            "muscle_group": "chest",
            "equipment": "dumbbell",
            "type": "strength",
            "met": 5,
            "region": "upper",
        },
    )
    assert r.status_code == 201, r.text
    problem(
        create(world, {"scope": "exercise", "exercise_id": r.json()["id"], "text": "x"}),
        404,
        "not_found",
    )


def test_athletes_cannot_create_notes_even_on_themselves(world: World) -> None:  # noqa: F811
    before = _count(world)
    for who in (world.ana, world.bob):
        for athlete in ("me", who.id):
            r = who.client.post(notes_url(athlete), json=day_note())
            assert problem(r, 403, "wrong_role")
    assert problem(
        world.ana.client.post(notes_url(world.bob.id), json=day_note()), 403, "wrong_role"
    )
    assert _count(world) == before


@pytest.mark.parametrize("who", ["dan", "eve", "fay", "gus"])
def test_unlinked_coaches_cannot_create(world: World, who: str) -> None:  # noqa: F811
    before = _count(world)
    problem(create(world, day_note(), who), 403, "not_linked")
    assert _count(world) == before


def _count(w: World) -> int:
    with Session(w.engine) as db:
        return len(db.scalars(select(CoachNote.id)).all())


# ───────────── notification ─────────────


def test_one_coach_note_notification_per_note_with_ids_only(world: World) -> None:  # noqa: F811
    secret = "zebra-unique-note-body-4821"
    with Session(world.engine) as db:
        before = len(
            db.scalars(
                select(Notification.id).where(
                    Notification.user_id == world.ana.id, Notification.type == "coach_note"
                )
            ).all()
        )
    r = create(world, day_note(text_=secret))
    assert r.status_code == 201
    with Session(world.engine) as db:
        rows = db.scalars(
            select(Notification).where(
                Notification.user_id == world.ana.id, Notification.type == "coach_note"
            )
        ).all()
    assert len(rows) == before + 1
    (newest,) = [n for n in rows if str(n.payload.get("note_id")) == r.json()["id"]]
    assert newest.payload == {
        "note_id": r.json()["id"],
        "date": "2026-10-22",
        "actor": {"id": str(world.cleo.id), "role": "coach"},
    }
    assert secret not in str(newest.payload)
    coach_types = {n["type"] for n in world.cleo.client.get(f"{API}/notifications").json()["items"]}
    assert "coach_note" not in coach_types


def test_edit_and_failed_create_add_no_notification(world: World) -> None:  # noqa: F811
    note = create(world, day_note()).json()
    count = _notifications(world)
    world.cleo.client.put(f"{notes_url(world.ana.id)}/{note['id']}", json={"text": "changed"})
    create(world, {"scope": "day", "text": "x"})
    assert _notifications(world) == count


def _notifications(w: World) -> int:
    with Session(w.engine) as db:
        return len(
            db.scalars(select(Notification.id).where(Notification.type == "coach_note")).all()
        )


# ───────────── list and day view ─────────────


def test_list_is_newest_first_and_filters(world: World) -> None:  # noqa: F811
    session = new_session(world)
    exercise_id = session["exercises"][0]["exercise"]["id"]
    clock = world.app.state.clock
    d = create(world, day_note("2026-12-01", "d-note")).json()
    clock.advance(seconds=1)
    s = create(world, {"scope": "session", "session_id": session["id"], "text": "s-note"}).json()
    clock.advance(seconds=1)
    e = create(world, {"scope": "exercise", "exercise_id": exercise_id, "text": "e-note"}).json()

    def ids(**params: Any) -> list[str]:
        r = world.ana.client.get(notes_url("me"), params=params)
        assert r.status_code == 200, r.text
        assert_matches_schema(r.json(), "NoteList")
        return [n["id"] for n in r.json()["items"]]

    everything = ids()
    assert everything.index(e["id"]) < everything.index(s["id"]) < everything.index(d["id"])
    assert ids(scope="day", **{"from": "2026-12-01", "to": "2026-12-01"}) == [d["id"]]
    assert ids(**{"from": "2026-12-02", "to": "2026-12-31"}) == []
    assert d["id"] not in ids(scope="session")
    assert ids(session_id=session["id"]) == [s["id"]]
    assert ids(exercise_id=exercise_id, scope="exercise")[0] == e["id"]
    assert ids(exercise_id=str(uuid.uuid4())) == []
    linked = world.cleo.client.get(notes_url(world.ana.id))
    assert linked.status_code == 200
    assert [n["id"] for n in linked.json()["items"]] == everything


def test_list_is_denied_to_strangers_and_unlinked_coaches(world: World) -> None:  # noqa: F811
    for who in (world.bob, world.dan, world.eve):
        problem(who.client.get(notes_url(world.ana.id)), 403, "not_linked")


def test_day_view_has_notes_of_the_day_its_session_and_its_exercises(world: World) -> None:  # noqa: F811
    session = new_session(world)
    day = session["date"]
    exercise_id = session["exercises"][0]["exercise"]["id"]
    other_day = "2026-01-05"
    mine = {
        create(world, day_note(day, "on the day")).json()["id"],
        create(
            world, {"scope": "session", "session_id": session["id"], "text": "on session"}
        ).json()["id"],
        create(
            world,
            {
                "scope": "exercise",
                "exercise_id": exercise_id,
                "session_id": session["id"],
                "text": "on exercise",
            },
        ).json()["id"],
        create(world, {"scope": "exercise", "exercise_id": exercise_id, "text": "standing"}).json()[
            "id"
        ],
    }
    elsewhere = create(world, day_note(other_day, "other day")).json()["id"]
    for who, athlete in ((world.ana, "me"), (world.cleo, world.ana.id)):
        r = who.client.get(f"{API}/athletes/{athlete}/days/{day}")
        assert r.status_code == 200, r.text
        assert_matches_schema(r.json(), "DayView")
        got = {n["id"] for n in r.json()["notes"]}
        assert mine <= got
        assert elsewhere not in got


# ───────────── author access: edit and delete ─────────────


def test_only_the_author_can_edit_and_delete(world: World) -> None:  # noqa: F811
    note = create(world, day_note()).json()
    url = f"{notes_url(world.ana.id)}/{note['id']}"
    before = _snapshot(world)
    # athlete (owner): 403 forbidden; other coach, stranger, former coach: 403 not_linked
    for who, code in (
        (world.ana, "forbidden"),
        (world.dan, "not_linked"),
        (world.bob, "not_linked"),
        (world.gus, "not_linked"),
    ):
        problem(who.client.put(url, json={"text": "hijack"}), 403, code)
        problem(who.client.delete(url), 403, code)
    assert world.anonymous.put(url, json={"text": "x"}).status_code == 401
    assert world.anonymous.delete(url).status_code == 401
    assert _snapshot(world) == before
    r = world.cleo.client.put(url, json={"text": "edited"})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "edited"
    assert r.json()["id"] == note["id"]
    assert_matches_schema(r.json(), "Note")
    assert world.cleo.client.delete(url).status_code == 204
    problem(world.cleo.client.delete(url), 404, "not_found")
    problem(world.cleo.client.put(url, json={"text": "x"}), 404, "not_found")


def test_edit_validates_text(world: World) -> None:  # noqa: F811
    note = create(world, day_note()).json()
    url = f"{notes_url(world.ana.id)}/{note['id']}"
    for body in ({"text": ""}, {"text": "x" * 2001}, {}, {"text": "x", "scope": "day"}):
        problem(world.cleo.client.put(url, json=body), 422, "validation_error")


def test_a_note_id_of_another_athlete_is_404_for_the_coach(world: World) -> None:  # noqa: F811
    note = create(world, day_note()).json()
    url = f"{API}/athletes/{world.ana.id}/notes/{uuid.uuid4()}"
    problem(world.cleo.client.delete(url), 404, "not_found")
    assert note["id"]


def _snapshot(w: World) -> list[tuple[Any, ...]]:
    with Session(w.engine) as db:
        return [
            (n.id, n.text, n.updated_at)
            for n in db.scalars(select(CoachNote).order_by(CoachNote.id))
        ]


def test_every_author_operation_is_covered_here() -> None:
    authored = {o.id for o in OPERATIONS if o.access == "author"}
    assert authored == {
        "PUT /athletes/{athlete_id}/notes/{note_id}",
        "DELETE /athletes/{athlete_id}/notes/{note_id}",
    }


# ───────────── the link ends (F16.1, D84) ─────────────


def test_notes_stay_visible_to_the_athlete_after_the_link_ends(world: World) -> None:  # noqa: F811
    jo = _person(world.app, "jo@x.test", "coach")
    try:
        link = _link(world.bob, jo)
        assert jo.client.post(f"{API}/coach-links/{link}/approve").status_code == 200
        url = notes_url(world.bob.id)
        r = jo.client.post(url, json=day_note(text_="from jo"))
        assert r.status_code == 201, r.text
        note_id = r.json()["id"]
        assert world.bob.client.post(f"{API}/coach-links/{link}/end").status_code == 200

        # The former coach loses create, list, edit and delete at once.
        problem(jo.client.post(url, json=day_note()), 403, "not_linked")
        problem(jo.client.get(url), 403, "not_linked")
        problem(jo.client.put(f"{url}/{note_id}", json={"text": "x"}), 403, "not_linked")
        problem(jo.client.delete(f"{url}/{note_id}"), 403, "not_linked")
        problem(jo.client.get(f"{API}/athletes/{world.bob.id}/days/2026-10-22"), 403, "not_linked")

        # The athlete still reads it, in the list and in the day view.
        listed = world.bob.client.get(url).json()["items"]
        assert [n["id"] for n in listed] == [note_id]
        assert listed[0]["text"] == "from jo"
        day = world.bob.client.get(f"{API}/athletes/me/days/2026-10-22").json()
        assert [n["id"] for n in day["notes"]] == [note_id]
        # ...but cannot change it (not the author).
        problem(world.bob.client.delete(f"{url}/{note_id}"), 403, "forbidden")
    finally:
        jo.client.__exit__(None, None, None)


# ───────────── cascade ─────────────


def test_deleting_the_authors_account_removes_their_notes(world: World) -> None:  # noqa: F811
    kay = _person(world.app, "kay@x.test", "coach")
    try:
        hal = _person(world.app, "hal@x.test", "athlete")
        try:
            link = _link(hal, kay)
            assert kay.client.post(f"{API}/coach-links/{link}/approve").status_code == 200
            assert kay.client.post(notes_url(hal.id), json=day_note()).status_code == 201
            with Session(world.engine) as db:
                db.execute(text("delete from users where id = :i"), {"i": kay.id})
                db.commit()
                left = db.scalars(select(CoachNote).where(CoachNote.author_id == kay.id)).all()
            assert left == []
        finally:
            hal.client.__exit__(None, None, None)
    finally:
        kay.client.__exit__(None, None, None)


# ───────────── telemetry ─────────────


def test_note_text_never_reaches_logs_metrics_or_spans(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    captured = Captured(app, telemetry, span_exporter, metric_reader)
    secret = "quokka-private-note-9137"
    edited = "wombat-private-edit-5520"
    with TestClient(app) as coach, TestClient(app) as athlete:
        assert (
            athlete.post(f"{API}/auth/signup", json=signup_body(email="a@x.test")).status_code
            == 201
        )
        c = coach.post(
            f"{API}/auth/signup", json=signup_body(email="c@x.test", role="coach")
        ).json()
        me = athlete.get(f"{API}/me").json()
        link = athlete.post(f"{API}/coach-links", json={"coach_id": c["id"]}).json()["id"]
        assert coach.post(f"{API}/coach-links/{link}/approve").status_code == 200
        url = notes_url(me["id"])
        note = coach.post(url, json=day_note(text_=secret))
        assert note.status_code == 201, note.text
        assert coach.put(f"{url}/{note.json()['id']}", json={"text": edited}).status_code == 200
        assert athlete.get(url).status_code == 200
        assert coach.delete(f"{url}/{note.json()['id']}").status_code == 204
        # a rejected body must not echo the text either
        assert coach.post(url, json={"scope": "day", "text": secret}).status_code == 422
    blob = json_logs.text
    for span in captured.spans():
        blob += str(span.to_json())
    data = captured.metric_reader.get_metrics_data()
    assert data is not None
    blob += str(data.to_json())
    for value in (secret, edited):
        assert value not in blob
