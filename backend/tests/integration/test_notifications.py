"""#45 F17 notifications against real Postgres: `notify`, the three endpoints (pagination, read,
read-all), authorization, the `content_removed` collector (D66, D71) and telemetry privacy."""

import datetime as dt
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Notification, User
from app.services import notifications
from tests.conftest import JsonLogs, captured_telemetry, make_settings
from tests.contract import assert_matches_schema, contract
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem, signup_body

N = "/api/v1/notifications"
ME = "/api/v1/me"
T0 = dt.datetime(2026, 10, 20, 8, 0, tzinfo=dt.UTC)


def at(minutes: int) -> dt.datetime:
    return T0 + dt.timedelta(minutes=minutes)


def user_id(api: Api, client: TestClient | None = None) -> uuid.UUID:
    return uuid.UUID((client or api.client).get(ME).json()["id"])


def add(
    api: Api, uid: uuid.UUID, when: dt.datetime, type_: Any = "recalc_prompt", **payload: Any
) -> uuid.UUID:
    """One notification via `notify` (the only producer path); returns its id."""
    with Session(api.app.state.engine) as db:
        nid = notifications.notify(db, uid, type_, payload, when)
        db.commit()
    assert nid is not None
    return nid


def second_user(api: Api, email: str = "bo@x.test") -> tuple[TestClient, uuid.UUID]:
    client = api.new_client()
    assert client.post("/api/v1/auth/signup", json=signup_body(email=email)).status_code == 201
    return client, uuid.UUID(client.get(ME).json()["id"])


@pytest.fixture
def ana(api: Api) -> Api:
    assert api.signup().status_code == 201
    return api


def rows(api: Api, uid: uuid.UUID) -> list[Notification]:
    with Session(api.app.state.engine) as db:
        return list(db.scalars(select(Notification).where(Notification.user_id == uid)))


# ───────────── notify ─────────────


def test_notify_rejects_payload_keys_outside_the_contract(ana: Api) -> None:
    with Session(ana.app.state.engine) as db:
        with pytest.raises(ValueError, match="food_name"):
            notifications.notify(db, user_id(ana), "content_removed", {"food_name": "x"}, NOW)
        db.rollback()
    assert rows(ana, user_id(ana)) == []


def test_notify_is_unique_per_user_type_and_suggestion(ana: Api) -> None:
    uid, sid = user_id(ana), uuid.uuid4()
    with Session(ana.app.state.engine) as db:
        first = notifications.notify(db, uid, "calorie_suggestion", {"suggestion_id": sid}, NOW)
        again = notifications.notify(db, uid, "calorie_suggestion", {"suggestion_id": sid}, NOW)
        other_type = notifications.notify(db, uid, "recalc_prompt", {"suggestion_id": sid}, NOW)
        db.commit()
    assert first is not None and again is None and other_type is not None
    assert len(rows(ana, uid)) == 2


def test_notify_writes_in_the_callers_transaction(ana: Api) -> None:
    uid = user_id(ana)
    with Session(ana.app.state.engine) as db:
        notifications.notify(db, uid, "recalc_prompt", {"suggestion_id": uuid.uuid4()}, NOW)
        db.rollback()
    assert rows(ana, uid) == []


def test_deleting_a_user_leaves_no_notification_rows(ana: Api) -> None:
    uid = user_id(ana)
    add(ana, uid, NOW, suggestion_id=uuid.uuid4())
    _, other_id = second_user(ana)
    add(ana, other_id, NOW, suggestion_id=uuid.uuid4())
    with Session(ana.app.state.engine) as db:
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        db.commit()
        assert db.scalar(select(func.count()).select_from(Notification)) == 1
        assert db.scalar(select(func.count()).where(Notification.user_id == uid)) == 0


# ───────────── GET /notifications ─────────────


def test_list_is_newest_first_owner_only_with_the_full_unread_count(ana: Api) -> None:
    uid = user_id(ana)
    _, other_id = second_user(ana)
    old = add(ana, uid, at(1), suggestion_id=uuid.uuid4())
    new = add(ana, uid, at(3), "calorie_suggestion", suggestion_id=uuid.uuid4())
    add(ana, other_id, at(2), suggestion_id=uuid.uuid4())
    assert ana.client.post(f"{N}/{old}/read").status_code == 200
    r = ana.client.get(N)
    assert r.status_code == 200, r.text
    body = r.json()
    assert_matches_schema(body, "NotificationPage")
    assert [i["id"] for i in body["items"]] == [str(new), str(old)]
    assert body["unread_count"] == 1 and body["next_cursor"] is None
    only = ana.client.get(N, params={"unread_only": "true"}).json()
    assert [i["id"] for i in only["items"]] == [str(new)]
    assert only["unread_count"] == 1
    assert ana.client.get(ME).json()["unread_notification_count"] == 1


def test_cursor_pagination_over_three_pages_with_equal_timestamps(ana: Api) -> None:
    uid = user_id(ana)
    made = {str(add(ana, uid, at(i // 2), suggestion_id=uuid.uuid4())) for i in range(5)}
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = ana.client.get(N, params=params).json()
        assert_matches_schema(body, "NotificationPage")
        assert body["unread_count"] == 5  # all unread, not just the page
        seen += [i["id"] for i in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and len(seen) == 5 and set(seen) == made


@pytest.mark.parametrize("cursor", ["!!!", "bm90LWpzb24", "WyJ4IiwgInkiXQ"])
def test_bad_cursor_is_400(ana: Api, cursor: str) -> None:
    problem(ana.client.get(N, params={"cursor": cursor}), 400, "bad_request")


@pytest.mark.parametrize("limit", [0, 101])
def test_limit_out_of_range_is_400(ana: Api, limit: int) -> None:
    assert ana.client.get(N, params={"limit": limit}).status_code in (400, 422)


# ───────────── POST /notifications/{id}/read ─────────────


def test_read_sets_read_at_is_idempotent_and_lowers_the_counts(ana: Api) -> None:
    uid = user_id(ana)
    a = add(ana, uid, at(1), suggestion_id=uuid.uuid4())
    add(ana, uid, at(2), suggestion_id=uuid.uuid4())
    assert ana.client.get(ME).json()["unread_notification_count"] == 2
    ana.clock.set(NOW)
    first = ana.client.post(f"{N}/{a}/read")
    assert first.status_code == 200, first.text
    assert_matches_schema(first.json(), "Notification")
    assert first.json()["read_at"] is not None
    ana.clock.set(NOW + dt.timedelta(hours=3))
    second = ana.client.post(f"{N}/{a}/read")
    assert second.status_code == 200
    assert second.json()["read_at"] == first.json()["read_at"]
    assert ana.client.get(N).json()["unread_count"] == 1
    assert ana.client.get(ME).json()["unread_notification_count"] == 1


# ───────────── POST /notifications/read-all ─────────────


def test_read_all_returns_the_exact_count_and_leaves_other_users_alone(ana: Api) -> None:
    uid = user_id(ana)
    bo, bo_id = second_user(ana)
    add(ana, uid, at(1), suggestion_id=uuid.uuid4())
    done = add(ana, uid, at(2), suggestion_id=uuid.uuid4())
    add(ana, uid, at(3), "content_removed")
    add(ana, bo_id, at(4), suggestion_id=uuid.uuid4())
    assert ana.client.post(f"{N}/{done}/read").status_code == 200
    first = ana.client.post(f"{N}/read-all")
    assert first.status_code == 200
    assert_matches_schema(first.json(), "MarkAllReadResult")
    assert first.json() == {"updated": 2}
    assert ana.client.post(f"{N}/read-all").json() == {"updated": 0}
    assert ana.client.get(N).json()["unread_count"] == 0
    assert bo.get(N).json()["unread_count"] == 1
    assert all(r.read_at is None for r in rows(ana, bo_id))


# ───────────── authorization ─────────────

OPERATIONS = [
    ("get", "/notifications", "listNotifications"),
    ("post", "/notifications/{id}/read", "markNotificationRead"),
    ("post", "/notifications/read-all", "markAllNotificationsRead"),
]


def test_contract_marks_the_three_operations_authenticated_without_a_404() -> None:
    for method, path, operation_id in OPERATIONS:
        op = contract()["paths"][path.replace("{id}", "{notification_id}")][method]
        assert op["operationId"] == operation_id
        assert op["x-fitwise-access"] == "authenticated"
        assert "401" in op["responses"] and "404" not in op["responses"]


@pytest.mark.parametrize(("method", "path", "_op"), OPERATIONS)
def test_every_endpoint_is_401_without_a_session(
    api: Api, method: str, path: str, _op: str
) -> None:
    url = "/api/v1" + path.replace("{id}", str(uuid.uuid4()))
    problem(api.client.request(method.upper(), url), 401, "not_authenticated")


def test_other_users_and_unknown_ids_are_403_and_change_nothing(ana: Api) -> None:
    uid = user_id(ana)
    bo, bo_id = second_user(ana)
    mine = add(ana, uid, at(1), suggestion_id=uuid.uuid4())
    theirs = add(ana, bo_id, at(2), suggestion_id=uuid.uuid4())
    problem(ana.client.post(f"{N}/{theirs}/read"), 403, "forbidden")
    problem(ana.client.post(f"{N}/{uuid.uuid4()}/read"), 403, "forbidden")
    problem(bo.post(f"{N}/{mine}/read"), 403, "forbidden")
    assert all(r.read_at is None for r in rows(ana, bo_id) + rows(ana, uid))
    assert [i["id"] for i in bo.get(N).json()["items"]] == [str(theirs)]
    assert [i["id"] for i in ana.client.get(N).json()["items"]] == [str(mine)]


def test_a_coach_cannot_read_an_athletes_notifications(ana: Api) -> None:
    uid = user_id(ana)
    nid = add(ana, uid, at(1), suggestion_id=uuid.uuid4())
    coach = ana.new_client()
    r = coach.post("/api/v1/auth/signup", json=signup_body(email="co@x.test", role="coach"))
    assert r.status_code == 201
    problem(coach.post(f"{N}/{nid}/read"), 403, "forbidden")
    assert coach.get(N).json()["items"] == []
    assert rows(ana, uid)[0].read_at is None


# ───────────── content_removed collector (D66, D71, F18.4, F18.6) ─────────────


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[Engine]:
    built = create_engine(migrated_database_url)
    yield built
    built.dispose()


def _user(conn: Connection, tag: str) -> uuid.UUID:
    uid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role, birth_date, units,"
            " timezone, disclaimer_accepted_at, created_at, updated_at) VALUES (:id, :email, 'x',"
            " 'T', 'athlete', '1990-01-01', 'metric', 'UTC', now(), now(), now())"
        ),
        {"id": uid, "email": f"{tag}-{uid}@example.com"},
    )
    return uid


def _food(conn: Connection, owner: uuid.UUID | None, name: str | None = None) -> uuid.UUID:
    fid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO food (id, owner_id, source, name, kcal_per_100g, protein_g_per_100g,"
            " carbs_g_per_100g, fat_g_per_100g, diet_tags, allergen_tags) VALUES (:id, :owner,"
            " 'custom', :name, 100, 10, 10, 10, '[]', '[]')"
        ),
        {"id": fid, "owner": owner, "name": name or f"f-{fid}"},
    )
    return fid


def _meal(conn: Connection, owner: uuid.UUID, foods: list[uuid.UUID]) -> uuid.UUID:
    mid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO meal (id, owner_id, source, name, slots) VALUES"
            " (:id, :owner, 'custom', :name, '[\"lunch\"]')"
        ),
        {"id": mid, "owner": owner, "name": f"m-{mid}"},
    )
    for position, fid in enumerate(foods):
        conn.execute(
            text(
                "INSERT INTO meal_item (id, meal_id, food_id, position, grams)"
                " VALUES (:id, :meal, :food, :pos, 100)"
            ),
            {"id": uuid.uuid4(), "meal": mid, "food": fid, "pos": position},
        )
    return mid


def _plan(conn: Connection, athlete: uuid.UUID, meals: list[uuid.UUID]) -> None:
    pid, did = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO plan (id, athlete_id, version, source, active, revision, created_at,"
            " updated_at) VALUES (:id, :a, 1, 'custom', true, 0, now(), now())"
        ),
        {"id": pid, "a": athlete},
    )
    conn.execute(
        text("INSERT INTO meal_day (id, plan_id, weekday, \"order\") VALUES (:id, :p, 'mon', 0)"),
        {"id": did, "p": pid},
    )
    for position, mid in enumerate(meals):
        conn.execute(
            text(
                'INSERT INTO planned_meal (id, meal_day_id, slot, "order", meal_id, portion_factor)'
                " VALUES (:id, :d, 'lunch', :o, :m, 1)"
            ),
            {"id": uuid.uuid4(), "d": did, "o": position, "m": mid},
        )


def _remove(engine: Engine, deleted: uuid.UUID) -> int:
    """What `deleteMe` (#50) does: collect, then delete, in one transaction."""
    with Session(engine) as db:
        count = notifications.notify_content_removed(db, deleted, NOW)
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": deleted})
        db.commit()
    return count


def _inbox(engine: Engine, uid: uuid.UUID) -> list[Notification]:
    with Session(engine) as db:
        return list(db.scalars(select(Notification).where(Notification.user_id == uid)))


def test_one_notification_per_affected_user_however_many_rows(engine: Engine) -> None:
    with engine.begin() as conn:
        a, b, c = _user(conn, "a"), _user(conn, "b"), _user(conn, "c")
        a_food, a_meal = _food(conn, a), None
        a_meal = _meal(conn, a, [a_food])
        # b: three meals with several items of a's food, and a plan with several of a's meals
        _meal(conn, b, [a_food, a_food])
        _meal(conn, b, [a_food])
        _plan(conn, b, [a_meal, a_meal, _meal(conn, b, [])])
        # c is unaffected
        _plan(conn, c, [_meal(conn, c, [_food(conn, c)])])
    assert _remove(engine, a) == 1
    (only,) = _inbox(engine, b)
    assert only.type == "content_removed" and only.payload == {} and only.read_at is None
    assert _inbox(engine, c) == [] and _inbox(engine, a) == []


def test_food_only_and_planned_meal_only_cases_each_notify(engine: Engine) -> None:
    with engine.begin() as conn:
        a, b, c = _user(conn, "a"), _user(conn, "b"), _user(conn, "c")
        _meal(conn, b, [_food(conn, a)])  # b: only a food in a meal
        _plan(conn, c, [_meal(conn, a, [])])  # c: only a planned meal
    assert _remove(engine, a) == 2
    assert len(_inbox(engine, b)) == 1 and len(_inbox(engine, c)) == 1


def test_a_user_with_both_a_food_and_a_planned_meal_gets_one(engine: Engine) -> None:
    with engine.begin() as conn:
        a, b = _user(conn, "a"), _user(conn, "b")
        _meal(conn, b, [_food(conn, a)])
        _plan(conn, b, [_meal(conn, a, [])])
    assert _remove(engine, a) == 1
    assert len(_inbox(engine, b)) == 1


def test_a_user_whose_account_no_longer_exists_gets_none(engine: Engine) -> None:
    with engine.begin() as conn:
        a, b, c = _user(conn, "a"), _user(conn, "b"), _user(conn, "c")
        a_meal = _meal(conn, a, [])
        _meal(conn, b, [_food(conn, a)])
        _plan(conn, c, [a_meal])
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": b})
    assert _remove(engine, a) == 1
    assert len(_inbox(engine, c)) == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Notification)) == 1


def test_a_collector_run_for_a_user_nobody_depends_on_notifies_nobody(engine: Engine) -> None:
    with engine.begin() as conn:
        a, b = _user(conn, "a"), _user(conn, "b")
        _meal(conn, a, [_food(conn, a)])
        _plan(conn, a, [_meal(conn, a, [])])
        _plan(conn, b, [_meal(conn, b, [])])
    assert _remove(engine, a) == 0
    assert _inbox(engine, b) == []


def test_the_collector_rolls_back_with_the_deletion(engine: Engine) -> None:
    with engine.begin() as conn:
        a, b = _user(conn, "a"), _user(conn, "b")
        _meal(conn, b, [_food(conn, a)])
    with Session(engine) as db:
        assert notifications.notify_content_removed(db, a, NOW) == 1
        db.rollback()
    assert _inbox(engine, b) == []


# ───────────── rule 6: no names in telemetry ─────────────


def test_content_removed_scenario_leaks_no_names_into_logs_spans_or_metrics(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    food_name = "Zanzibar Quinoa Crunch"
    settings = make_settings(migrated_database_url)
    telemetry, exporter, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    with TestClient(app) as ana, TestClient(app) as bo, Session(app.state.engine) as db:
        sign = signup_body(email="ana-secret@x.test", display_name="Ana Zorrilla")
        assert ana.post("/api/v1/auth/signup", json=sign).status_code == 201
        sign = signup_body(email="bo-secret@x.test", display_name="Bo Zorrilla")
        assert bo.post("/api/v1/auth/signup", json=sign).status_code == 201
        a = db.scalars(select(User.id).where(User.email == "ana-secret@x.test")).one()
        b = db.scalars(select(User.id).where(User.email == "bo-secret@x.test")).one()
        db.commit()
        with app.state.engine.begin() as conn:
            _meal(conn, b, [_food(conn, a, food_name)])
        notifications.notify_content_removed(db, a, NOW)
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": a})
        db.commit()
        listing = bo.get(N)
        assert [i["type"] for i in listing.json()["items"]] == ["content_removed"]
        nid = listing.json()["items"][0]["id"]
        assert bo.post(f"{N}/{nid}/read").status_code == 200
        assert bo.post(f"{N}/read-all").status_code == 200
        assert bo.get(ME).status_code == 200
    blob = (
        json_logs.text
        + repr([(dict(s.attributes or {}), s.name) for s in exporter.get_finished_spans()])
        + repr(reader.get_metrics_data())
    )
    for secret in (food_name, "Zanzibar", "ana-secret", "bo-secret", "Zorrilla"):
        assert secret not in blob
    with Session(app.state.engine) as db:
        stored = repr([r.payload for r in db.scalars(select(Notification))])
    assert "Zanzibar" not in stored
