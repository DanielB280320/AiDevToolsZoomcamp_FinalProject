# ruff: noqa: S608  (table and column names come from schema introspection, never from input)
"""#50 F18 data ownership against real Postgres: the export ZIP holds only the caller's data
(F18.1), `POST /me/delete` (D48), a schema-introspected "nothing remains" check (F18.2), coach
deletion (F18.5, link ends, notes removed), coach cannot act on an athlete's account (F18.3) and
the single `content_removed` notification (F18.4, F18.6; D66, D71, D79(4))."""

import io
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from app.main import create_app
from app.seed import run_seed
from tests.conftest import Captured, JsonLogs, captured_telemetry, make_settings
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, PASSWORD, Api, problem, signup_body
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_user_delete_food_cascade import _food, _meal

API = "/api/v1"
EXPORT_FILES = {
    "profile.json",
    "plan_versions.json",
    "set_logs.csv",
    "meal_logs.csv",
    "body_metrics.csv",
    "extra_activities.csv",
    "suggestions.csv",
}


@dataclass
class Person:
    client: TestClient
    id: uuid.UUID
    email: str


def _person(api: Api, email: str, role: str = "athlete", *, onboard: bool = False) -> Person:
    client = api.new_client()
    r = client.post(
        f"{API}/auth/signup", json=signup_body(email=email, role=role, display_name=email[:3])
    )
    assert r.status_code == 201, r.text
    if onboard:
        r = client.post(ONBOARD, json=onboarding())
        assert r.status_code == 201, r.text
    return Person(client, uuid.UUID(r.json()["id"]) if not onboard else _me(client), email)


def _me(client: TestClient) -> uuid.UUID:
    return uuid.UUID(client.get(f"{API}/me").json()["id"])


@dataclass
class World:
    api: Api
    ana: Person  # athlete with data, linked to cleo
    bob: Person  # stranger athlete with data
    cleo: Person  # ana's coach

    @property
    def engine(self) -> Engine:
        engine: Engine = self.api.app.state.engine
        return engine


def _link(athlete: Person, coach: Person) -> None:
    r = athlete.client.post(f"{API}/coach-links", json={"coach_id": str(coach.id)})
    assert r.status_code == 201, r.text
    r = coach.client.post(f"{API}/coach-links/{r.json()['id']}/approve")
    assert r.status_code == 200, r.text


def _log_something(p: Person, day: str = "2026-11-02") -> None:
    r = p.client.get(f"{API}/athletes/me/days/{day}")
    assert r.status_code == 200, r.text
    session = r.json()["session"]
    assert session is not None
    first = session["exercises"][0]
    kind = first["exercise"]["type"]
    values = {"seconds": 30} if kind == "timed" else {"reps": 8, "weight_kg": 20}
    r = p.client.post(
        f"{API}/sessions/{session['id']}/sets",
        json={
            "exercise_id": first["exercise"]["id"],
            "planned_exercise_id": first["planned_exercise_id"],
            "set_no": 1,
            **values,
        },
    )
    assert r.status_code == 201, r.text
    with p.client.app.state.engine.connect() as conn:  # type: ignore[attr-defined]
        food = conn.execute(text("SELECT id FROM food WHERE owner_id IS NULL LIMIT 1")).scalar_one()
    r = p.client.post(
        f"{API}/athletes/me/meal-logs",
        json={
            "date": "2026-10-22",
            "planned_meal_id": None,
            "status": "extra",
            "items": [{"food_id": str(food), "grams": 120}],
        },
    )
    assert r.status_code in (200, 201), r.text


@pytest.fixture
def world(api: Api) -> World:
    with Session(api.app.state.engine) as db:
        run_seed(db)
    ana = _person(api, "ana@x.test", onboard=True)
    bob = _person(api, "bob@x.test", onboard=True)
    cleo = _person(api, "cleo@x.test", "coach")
    _link(ana, cleo)
    return World(api, ana, bob, cleo)


def _zip(r: Any) -> dict[str, str]:
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        return {n: archive.read(n).decode() for n in archive.namelist()}


def _delete(p: Person, password: str = PASSWORD) -> Any:
    return p.client.post(f"{API}/me/delete", json={"password": password})


# ───────────── F18.1 export ─────────────


def test_export_is_a_zip_with_the_documented_files(world: World) -> None:
    r = world.ana.client.get(f"{API}/me/export")
    assert r.headers["content-type"] == "application/zip"
    assert (
        r.headers["content-disposition"] == 'attachment; filename="fitwise-export-2026-10-22.zip"'
    )
    files = _zip(r)
    assert set(files) == EXPORT_FILES
    assert "ana@x.test" in files["profile.json"]
    assert "password" not in files["profile.json"]
    assert files["body_metrics.csv"].count("\n") >= 2  # header + the onboarding weigh-in
    assert files["plan_versions.json"].startswith("[")


def test_export_contains_no_value_of_the_other_user(world: World) -> None:
    ana_id, bob_id = str(world.ana.id), str(world.bob.id)
    world.bob.client.post(
        f"{API}/athletes/me/body-metrics", json={"date": "2026-10-22", "weight_kg": 91.23}
    )
    with world.engine.begin() as conn:
        # Bob is also a plan author on Ana's plan: that id must not leak either.
        conn.execute(
            text("UPDATE plan SET created_by = :b WHERE athlete_id = :a"),
            {"b": bob_id, "a": ana_id},
        )
    ana_files = _zip(world.ana.client.get(f"{API}/me/export"))
    bob_files = _zip(world.bob.client.get(f"{API}/me/export"))
    ana_blob, bob_blob = "\n".join(ana_files.values()), "\n".join(bob_files.values())
    assert bob_id not in ana_blob and "bob@x.test" not in ana_blob and "91.23" not in ana_blob
    assert ana_id not in bob_blob and "ana@x.test" not in bob_blob
    assert world.cleo.id.hex not in ana_blob.replace("-", "")


def test_export_requires_a_session(world: World) -> None:
    assert world.api.new_client().get(f"{API}/me/export").status_code == 401


# ───────────── POST /me/delete ─────────────


def test_wrong_password_is_403_and_deletes_nothing(world: World) -> None:
    problem(_delete(world.ana, "not-the-password"), 403, "forbidden")
    assert world.ana.client.get(f"{API}/me").status_code == 200


@pytest.mark.parametrize("body", [{}, {"password": ""}, {"password": "x", "extra": 1}])
def test_invalid_body_is_rejected(world: World, body: dict[str, Any]) -> None:
    r = world.ana.client.post(f"{API}/me/delete", json=body)
    assert r.status_code in (400, 422), r.text
    assert world.ana.client.get(f"{API}/me").status_code == 200


def test_delete_requires_a_session(world: World) -> None:
    r = world.api.new_client().post(f"{API}/me/delete", json={"password": PASSWORD})
    assert r.status_code == 401


def test_correct_password_is_204_clears_the_cookie_and_ends_the_session(world: World) -> None:
    r = _delete(world.ana)
    assert r.status_code == 204 and r.content == b""
    assert "Max-Age=0" in r.headers["set-cookie"] or "expires" in r.headers["set-cookie"].lower()
    assert world.ana.client.get(f"{API}/me").status_code == 401
    assert world.api.login("ana@x.test").status_code == 401
    assert world.bob.client.get(f"{API}/me").status_code == 200


# ───────────── F18.2 nothing remains ─────────────


def _reachable(engine: Engine, user_id: uuid.UUID) -> dict[str, set[Any]]:
    """Every row that depends on the user: walk foreign keys from `users` to their children,
    skipping `SET NULL` (the row survives, the reference becomes null)."""
    insp = inspect(engine)
    children: dict[str, list[tuple[str, str, str]]] = {}
    for table in insp.get_table_names():
        for fk in insp.get_foreign_keys(table):
            if (fk["options"] or {}).get("ondelete") == "SET NULL":
                continue
            children.setdefault(fk["referred_table"], []).append(
                (table, fk["constrained_columns"][0], fk["referred_columns"][0])
            )
    found: dict[str, set[Any]] = {"users": {user_id}}
    frontier = [("users", "id", {user_id})]
    with engine.connect() as conn:
        while frontier:
            table, _column, ids = frontier.pop()
            for child, column, referred in children.get(table, []):
                values = {
                    row[0]
                    for row in conn.execute(
                        text(f'SELECT id FROM "{child}" WHERE "{column}" = ANY(:ids)')
                        if _has_id(insp, child)
                        else text(f'SELECT "{column}" FROM "{child}" WHERE "{column}" = ANY(:ids)'),
                        {"ids": _referenced_ids(conn, table, referred, ids)},
                    )
                }
                new = values - found.get(child, set())
                if new:
                    found.setdefault(child, set()).update(new)
                    pk = "id" if _has_id(insp, child) else column
                    frontier.append((child, pk, new))
    return found


def _has_id(insp: Any, table: str) -> bool:
    return any(c["name"] == "id" for c in insp.get_columns(table))


def _referenced_ids(conn: Any, table: str, referred: str, ids: set[Any]) -> list[Any]:
    if referred == "id":
        return list(ids)
    rows = conn.execute(
        text(f'SELECT "{referred}" FROM "{table}" WHERE id = ANY(:ids)'), {"ids": list(ids)}
    )
    return [r[0] for r in rows]


def test_after_deletion_no_row_referencing_the_user_remains(world: World) -> None:
    _log_something(world.ana)
    note = world.cleo.client.post(
        f"{API}/athletes/{world.ana.id}/notes",
        json={"scope": "day", "date": "2026-10-22", "text": "x"},
    )
    assert note.status_code == 201, note.text
    with world.engine.begin() as conn:
        food = _food(conn, world.ana.id)
        _meal(conn, world.ana.id, [food])
    before = _reachable(world.engine, world.ana.id)
    assert {"plan", "session", "set_log", "meal", "targets", "coach_note"} <= set(before), before
    assert _delete(world.ana).status_code == 204
    with world.engine.connect() as conn:
        for table, ids in before.items():
            remaining = conn.execute(
                text(f'SELECT count(*) FROM "{table}" WHERE id = ANY(:ids)')
                if _has_id(inspect(world.engine), table)
                else text(f'SELECT count(*) FROM "{table}" WHERE false'),
                {"ids": list(ids)},
            ).scalar_one()
            assert remaining == 0, table
        # Direct references of any kind, found by introspection (later tables are covered).
        insp = inspect(world.engine)
        for table in insp.get_table_names():
            for fk in insp.get_foreign_keys(table):
                if fk["referred_table"] == "users":
                    column = fk["constrained_columns"][0]
                    count = conn.execute(
                        text(f'SELECT count(*) FROM "{table}" WHERE "{column}" = :u'),
                        {"u": world.ana.id},
                    ).scalar_one()
                    assert count == 0, f"{table}.{column}"
    # Bob is untouched.
    assert world.bob.client.get(f"{API}/athletes/me/plan").status_code == 200


# ───────────── F18.3 a coach cannot act on an athlete's account ─────────────


def test_a_linked_coach_deleting_or_exporting_acts_only_on_themselves(world: World) -> None:
    export = _zip(world.cleo.client.get(f"{API}/me/export"))
    assert str(world.ana.id) not in "\n".join(export.values())
    assert world.cleo.client.get(f"{API}/athletes/{world.ana.id}/export").status_code in (404, 405)
    assert world.cleo.client.post(f"{API}/athletes/{world.ana.id}/delete").status_code in (404, 405)
    # The password in the body is the coach's own: Ana's password changes nothing for Ana.
    assert _delete(world.cleo).status_code == 204
    assert world.ana.client.get(f"{API}/me").status_code == 200


# ───────────── F18.5 + coach deletion ─────────────


def test_deleting_a_coach_nulls_references_ends_links_and_removes_their_notes(
    world: World,
) -> None:
    ana, cleo = world.ana.id, world.cleo.id
    r = world.cleo.client.post(
        f"{API}/athletes/{ana}/notes", json={"scope": "day", "date": "2026-10-22", "text": "x"}
    )
    assert r.status_code == 201
    with world.engine.begin() as conn:
        conn.execute(
            text("UPDATE plan SET created_by = :c WHERE athlete_id = :a"), {"c": cleo, "a": ana}
        )
        conn.execute(
            text(
                "UPDATE training_day SET edited_by = :c WHERE plan_id IN"
                " (SELECT id FROM plan WHERE athlete_id = :a)"
            ),
            {"c": cleo, "a": ana},
        )
        conn.execute(
            text(
                "UPDATE meal_day SET edited_by = :c WHERE plan_id IN"
                " (SELECT id FROM plan WHERE athlete_id = :a)"
            ),
            {"c": cleo, "a": ana},
        )
        conn.execute(
            text(
                "INSERT INTO plan_change (id, plan_id, author_id, author_role, change, created_at)"
                " SELECT gen_random_uuid(), id, :c, 'coach', '{}', now() FROM plan"
                " WHERE athlete_id = :a"
            ),
            {"c": cleo, "a": ana},
        )
        conn.execute(
            text(
                "INSERT INTO suggestion (id, athlete_id, kind, status, rule, reason, inputs,"
                " payload, created_at, decided_by, decided_at) VALUES (gen_random_uuid(), :a,"
                " 'calories', 'accepted', 'r', 'r', '{}', '{}', now(), :c, now())"
            ),
            {"c": cleo, "a": ana},
        )
        plans = conn.execute(
            text("SELECT count(*) FROM plan WHERE athlete_id = :a"), {"a": ana}
        ).scalar_one()
    assert _delete(world.cleo).status_code == 204
    with world.engine.connect() as conn:

        def n(sql: str) -> int:
            return int(conn.execute(text(sql), {"a": ana}).scalar_one())

        assert n("SELECT count(*) FROM plan WHERE athlete_id = :a") == plans
        assert n("SELECT count(*) FROM plan WHERE athlete_id = :a AND created_by IS NOT NULL") == 0
        assert n("SELECT count(*) FROM training_day WHERE edited_by IS NOT NULL") == 0
        assert n("SELECT count(*) FROM meal_day WHERE edited_by IS NOT NULL") == 0
        assert (
            n(
                "SELECT count(*) FROM plan_change"
                " WHERE author_id IS NOT NULL AND author_role = 'coach'"
            )
            == 0
        )
        assert n("SELECT count(*) FROM plan_change WHERE author_role = 'coach'") == 1
        assert (
            n("SELECT count(*) FROM suggestion WHERE athlete_id = :a AND decided_by IS NULL") == 1
        )
        assert n("SELECT count(*) FROM coach_note") == 0
        assert n("SELECT count(*) FROM coach_link") == 0
    types = [n_["type"] for n_ in world.ana.client.get(f"{API}/notifications").json()["items"]]
    assert types.count("link_ended") == 1
    assert world.ana.client.get(f"{API}/me").json()["active_coach"] is None
    assert world.ana.client.get(f"{API}/athletes/me/plan").status_code == 200


def test_deleting_an_athlete_tells_their_coach_the_link_ended(world: World) -> None:
    assert _delete(world.ana).status_code == 204
    items = world.cleo.client.get(f"{API}/notifications").json()["items"]
    ended = [i for i in items if i["type"] == "link_ended"]
    assert len(ended) == 1 and ended[0]["payload"] == {}
    # Notifications that named the athlete (the link request) are gone with them.
    assert not [i for i in items if i["type"] == "link_request_received"]


# ───────────── F18.4 / F18.6 content_removed ─────────────


def _removed(p: Person) -> list[dict[str, Any]]:
    items = p.client.get(f"{API}/notifications").json()["items"]
    return [i for i in items if i["type"] == "content_removed"]


def test_one_content_removed_per_affected_user_however_many_rows(world: World) -> None:
    with world.engine.begin() as conn:
        f1, f2 = _food(conn, world.ana.id), _food(conn, world.ana.id)
        _meal(conn, world.bob.id, [f1, f2])
        _meal(conn, world.bob.id, [f1])
        # A meal of Ana's in Bob's plan (F18.6).
        mine = _meal(conn, world.ana.id, [])
        conn.execute(
            text(
                'INSERT INTO planned_meal (id, meal_day_id, slot, "order", meal_id, portion_factor)'
                " SELECT gen_random_uuid(), md.id, 'lunch', 99, :m, 1 FROM meal_day md"
                " JOIN plan p ON p.id = md.plan_id WHERE p.athlete_id = :b AND p.active LIMIT 1"
            ),
            {"m": mine, "b": world.bob.id},
        )
    assert _delete(world.ana).status_code == 204
    removed = _removed(world.bob)
    assert len(removed) == 1
    assert removed[0]["payload"] == {}


def test_no_notification_for_a_user_without_an_account_or_without_affected_content(
    world: World,
) -> None:
    carl = _person(world.api, "carl@x.test")
    with world.engine.begin() as conn:
        food = _food(conn, world.ana.id)
        _meal(conn, carl.id, [food])
    assert _delete(carl).status_code == 204  # carl is gone before ana is deleted
    assert _delete(world.ana).status_code == 204
    assert _removed(world.bob) == []
    with world.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM notification WHERE type = 'content_removed'")
            ).scalar_one()
            == 0
        )


def test_an_unlinked_user_is_notified_too(world: World) -> None:
    assert world.bob.client.get(f"{API}/coach-links").status_code == 200  # bob never linked
    with world.engine.begin() as conn:
        _meal(conn, world.bob.id, [_food(conn, world.ana.id)])
    assert _delete(world.ana).status_code == 204
    assert len(_removed(world.bob)) == 1


def test_a_failed_delete_leaves_no_notification(world: World) -> None:
    with world.engine.begin() as conn:
        _meal(conn, world.bob.id, [_food(conn, world.ana.id)])
    assert _delete(world.ana, "wrong-password").status_code == 403
    assert _removed(world.bob) == []


def test_deletion_never_puts_food_names_or_user_data_in_telemetry(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    captured = Captured(app, telemetry, span_exporter, metric_reader)
    with TestClient(app) as ana, TestClient(app) as bob:
        a = ana.post(f"{API}/auth/signup", json=signup_body(email="ana-secret@x.test"))
        b = bob.post(f"{API}/auth/signup", json=signup_body(email="bob-secret@x.test"))
        assert a.status_code == b.status_code == 201
        with app.state.engine.begin() as conn:
            food = _food(conn, uuid.UUID(a.json()["id"]))
            _meal(conn, uuid.UUID(b.json()["id"]), [food])
            name = conn.execute(
                text("SELECT name FROM food WHERE id = :f"), {"f": food}
            ).scalar_one()
        assert (
            ana.post(f"{API}/me/delete", json={"password": "wrong-password-1"}).status_code == 403
        )
        assert ana.post(f"{API}/me/delete", json={"password": PASSWORD}).status_code == 204
    blob = json_logs.text
    for span in captured.spans():
        blob += str(span.to_json())
    data = captured.metric_reader.get_metrics_data()
    assert data is not None
    blob += str(data.to_json())
    for secret in (name, "ana-secret", "bob-secret", PASSWORD, "wrong-password-1"):
        assert secret not in blob
