"""QA for #37 (F12 meal logging), independent of the implementer's tests: concurrent check-offs
and the IntegrityError fallback count once, telemetry carries no food names or quantities, grams
are stored metric, the eaten snapshot survives library edits, user deletion is never blocked by
`meal_log_item.food_id`, the migration downgrades and upgrades with data, and a new plan version
(D65: same meals, same created_at) does not rewrite a logged day."""

import datetime as dt
import logging
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Meal, MealDay, MealLog, MealLogItem, Plan, PlannedMeal, User
from app.services import meal_log as meal_log_service
from app.services.plans import (
    NewMealDay,
    NewPlannedExercise,
    NewPlannedMeal,
    NewTrainingDay,
    create_plan_version,
)
from tests.conftest import Captured, captured_telemetry, make_settings
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api
from tests.integration.test_meal_log import BASE, ME, THU, _day, _post, _seed_athlete
from tests.integration.test_user_delete_food_cascade import _alembic, _food, _user

SECRET_FOOD = "QA Secret Kale Smoothie"


@pytest.fixture
def captured(migrated_database_url: str) -> Iterator[tuple[Api, Captured]]:
    settings = make_settings(migrated_database_url)
    telemetry, spans, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    with TestClient(app) as client:
        api = Api(app=app, client=client, clock=app.state.clock)
        _seed_athlete(api)
        yield api, Captured(app, telemetry, spans, reader)


def _checkoffs(captured: Captured) -> float:
    return float(sum(p.value for p in captured.metric_points("fitwise_meal_checkoffs_total")))


def _rows(api: Api, model: Any) -> int:
    with Session(api.app.state.engine) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


# ───────────── F12.3 under concurrency ─────────────


def test_concurrent_checkoffs_with_a_barrier_create_one_row_and_count_once(
    captured: tuple[Api, Captured],
) -> None:
    api, cap = captured
    meals = _day(api.client)["meals"]
    for meal in meals:
        planned = meal["planned_meal"]["id"]
        barrier = threading.Barrier(6)

        def check(_: int, planned: str = planned, barrier: threading.Barrier = barrier) -> Any:
            barrier.wait(timeout=10)
            return _post(api.client, planned_meal_id=planned, status="eaten")

        with ThreadPoolExecutor(6) as pool:
            responses = list(pool.map(check, range(6)))
        codes = sorted(r.status_code for r in responses)
        assert codes == [200] * 5 + [201], codes
        assert len({r.json()["meal_log"]["id"] for r in responses}) == 1
    assert _rows(api, MealLog) == len(meals)
    assert _checkoffs(cap) == len(meals)


def test_losing_the_insert_race_returns_the_existing_log_and_does_not_count(
    captured: tuple[Api, Captured], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forces the IntegrityError branch: the pre-check misses the committed row, the partial
    unique index rejects the insert, and the request behaves as a repeat."""
    api, cap = captured
    planned = _day(api.client)["meals"][0]["planned_meal"]["id"]
    first = _post(api.client, planned_meal_id=planned, status="eaten")
    assert first.status_code == 201
    real = meal_log_service._existing
    calls = {"n": 0}

    def blind_once(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*args, **kwargs)

    monkeypatch.setattr(meal_log_service, "_existing", blind_once)
    again = _post(api.client, planned_meal_id=planned, status="eaten")
    assert calls["n"] == 2, "the fallback lookup after the unique violation did not run"
    assert again.status_code == 200, again.text
    assert again.json()["meal_log"]["id"] == first.json()["meal_log"]["id"]
    assert _rows(api, MealLog) == 1
    assert _checkoffs(cap) == 1


def test_extra_food_and_status_changes_do_not_count_as_checkoffs(
    captured: tuple[Api, Captured],
) -> None:
    api, cap = captured
    planned = _day(api.client)["meals"][0]["planned_meal"]
    food = planned["items"][0]["food"]["id"]
    assert _post(api.client, planned_meal_id=planned["id"], status="skipped").status_code == 201
    adjusted = _post(
        api.client,
        planned_meal_id=planned["id"],
        status="adjusted",
        items=[{"food_id": food, "grams": 42}],
    )
    assert adjusted.status_code == 200
    extra = _post(
        api.client, planned_meal_id=None, status="extra", items=[{"food_id": food, "grams": 10}]
    )
    assert extra.status_code == 201
    assert _checkoffs(cap) == 1  # only the first log of the planned meal (D70)


# ───────────── rule 6: telemetry privacy ─────────────


def test_meal_logging_telemetry_has_no_food_names_quantities_or_identity(
    captured: tuple[Api, Captured], caplog: pytest.LogCaptureFixture
) -> None:
    api, cap = captured
    caplog.set_level(logging.DEBUG)
    food = api.client.post(
        f"{BASE}/foods",
        json={
            "name": SECRET_FOOD,
            "kcal_per_100g": 123,
            "protein_g_per_100g": 7,
            "carbs_g_per_100g": 11,
            "fat_g_per_100g": 3,
        },
    ).json()["id"]
    planned = _day(api.client)["meals"][0]["planned_meal"]["id"]
    assert _post(api.client, planned_meal_id=planned, status="eaten").status_code == 201
    extra = _post(
        api.client,
        planned_meal_id=None,
        status="extra",
        slot="snack",
        items=[{"food_id": food, "grams": 987.6}],
    )
    assert extra.status_code == 201
    log_id = extra.json()["meal_log"]["id"]
    _day(api.client)
    assert api.client.delete(f"{ME}/meal-logs/{log_id}").status_code == 200

    forbidden = [SECRET_FOOD, "Kale", "987.6", "ana@x.test", food, log_id, planned]
    dumped: list[str] = []
    for span in cap.spans():
        dumped.append(span.name)
        dumped.extend(f"{k}={v!r}" for k, v in (span.attributes or {}).items())
        for event in span.events:
            dumped.append(event.name)
            dumped.extend(f"{k}={v!r}" for k, v in (event.attributes or {}).items())
    data = cap.metric_reader.get_metrics_data()
    assert data is not None
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                for point in metric.data.data_points:
                    dumped.extend(f"{k}={v!r}" for k, v in (point.attributes or {}).items())
    # The app's own loggers only; `httpx` is the test client logging its request URL.
    app_records = [r for r in caplog.records if not r.name.startswith("httpx")]
    assert any(r.name == "app.access" for r in app_records)
    dumped.extend(record.getMessage() for record in app_records)
    dumped.extend(str(record.__dict__) for record in app_records)
    blob = "\n".join(dumped)
    leaks = [value for value in forbidden if value in blob]
    assert not leaks, [(v, [line[:300] for line in dumped if v in line]) for v in leaks]
    routes = {
        s.attributes.get("http.route")
        for s in cap.server_spans()
        if s.attributes and "meal-logs" in str(s.attributes.get("http.route"))
    }
    assert routes <= {
        "/api/v1/athletes/{athlete_id}/meal-logs",
        "/api/v1/athletes/{athlete_id}/meal-logs/{meal_log_id}",
    }


# ───────────── rule 5 / rule 7: metric storage and snapshots ─────────────


def test_grams_are_stored_as_grams_for_an_imperial_user(migrated_database_url: str) -> None:
    settings = make_settings(migrated_database_url)
    app = create_app(settings)
    app.state.clock = FakeClock(NOW)
    with TestClient(app) as client:
        api = Api(app=app, client=client, clock=app.state.clock)
        _seed_athlete(api)
        with Session(app.state.engine) as session:
            session.execute(text("UPDATE users SET units = 'imperial'"))
            session.commit()
        planned = _day(client)["meals"][0]["planned_meal"]
        food = planned["items"][0]["food"]["id"]
        response = _post(
            client,
            planned_meal_id=planned["id"],
            status="adjusted",
            items=[{"food_id": food, "grams": 250.5}],
        )
        assert response.status_code == 201, response.text
        assert response.json()["meal_log"]["items"][0]["grams"] == 250.5
        with Session(app.state.engine) as session:
            assert session.scalars(select(MealLogItem.grams)).one() == 250.5


def test_eaten_keeps_the_planned_grams_when_the_library_meal_changes_later(
    captured: tuple[Api, Captured],
) -> None:
    api, _ = captured
    planned = _day(api.client)["meals"][0]["planned_meal"]
    logged = _post(api.client, planned_meal_id=planned["id"], status="eaten").json()["meal_log"]
    assert [i["grams"] for i in logged["items"]] == [i["grams"] for i in planned["items"]]
    with Session(api.app.state.engine) as session:
        session.execute(text("UPDATE meal_item SET grams = grams + 77"))
        session.commit()
    day = _day(api.client)
    after = next(m for m in day["meals"] if m["planned_meal"]["id"] == planned["id"])
    assert after["planned_meal"]["items"][0]["grams"] != planned["items"][0]["grams"]
    assert after["log"]["items"] == logged["items"]
    assert day["energy"]["eaten"]["kcal"] == logged["totals"]["kcal"]


def _plan_version_with_same_meals(api: Api) -> None:
    """What accepting a suggestion does (D65): a new version, same `created_at`. Here the meal
    days are copied unchanged, so for the athlete it is the same plan."""
    with Session(api.app.state.engine) as session:
        uid = session.scalars(select(User.id)).one()
        old = session.scalars(select(Plan).where(Plan.active.is_(True))).one()
        days = session.scalars(select(MealDay).where(MealDay.plan_id == old.id)).all()
        training = old.training_days[0].exercises[0]
        create_plan_version(
            session,
            athlete_id=uid,
            author_id=uid,
            source=old.source,
            days=[
                NewTrainingDay(
                    "mon",
                    "Day",
                    [
                        NewPlannedExercise(
                            training.exercise_id, 3, 90, "linear", 2.5, reps_min=8, reps_max=8
                        )
                    ],
                )
            ],
            meal_days=[
                NewMealDay(
                    d.weekday,
                    [NewPlannedMeal(m.slot, m.meal_id, m.portion_factor) for m in d.meals],
                )
                for d in days
            ],
            now=old.created_at,
        )
        session.commit()


def test_a_new_plan_version_does_not_rewrite_a_logged_day(captured: tuple[Api, Captured]) -> None:
    api, _ = captured
    before = _day(api.client)
    planned = before["meals"][0]["planned_meal"]["id"]
    first = _post(api.client, planned_meal_id=planned, status="eaten").json()
    assert first["nutrition_completion"] == pytest.approx(1 / 3, abs=1e-3)
    _plan_version_with_same_meals(api)
    after = _day(api.client)
    # Rule 7 / D70: the logged day keeps its check-off and its completion.
    assert after["nutrition_completion"] == pytest.approx(1 / 3, abs=1e-3)
    assert any(m["log"] is not None for m in after["meals"])


def test_the_same_meal_cannot_be_eaten_twice_across_plan_versions(
    captured: tuple[Api, Captured],
) -> None:
    api, cap = captured
    planned = _day(api.client)["meals"][0]["planned_meal"]["id"]
    once = _post(api.client, planned_meal_id=planned, status="eaten").json()
    _plan_version_with_same_meals(api)
    again_id = _day(api.client)["meals"][0]["planned_meal"]["id"]
    _post(api.client, planned_meal_id=again_id, status="eaten")
    assert _day(api.client)["energy"]["eaten"]["kcal"] == once["meal_log"]["totals"]["kcal"]
    assert _checkoffs(cap) == 1


def _shown(day: dict[str, Any]) -> set[str]:
    return {m["log"]["id"] for m in day["meals"] if m["log"]} | {
        e["id"] for e in day["extra_meal_logs"]
    }


def test_a_logged_planned_meal_is_visible_on_its_day(captured: tuple[Api, Captured]) -> None:
    api, _ = captured
    planned = _day(api.client)["meals"][0]["planned_meal"]["id"]
    log = _post(api.client, planned_meal_id=planned, status="eaten").json()["meal_log"]
    assert log["id"] in _shown(_day(api.client))


def test_a_log_that_counts_in_eaten_stays_visible_after_the_plan_is_replaced(
    captured: tuple[Api, Captured],
) -> None:
    """Every log that counts in `energy.eaten` must be visible (and undoable) on its day."""
    api, _ = captured
    planned = _day(api.client)["meals"][0]["planned_meal"]["id"]
    log = _post(api.client, planned_meal_id=planned, status="eaten").json()["meal_log"]
    _plan_version_with_same_meals(api)
    day = _day(api.client)
    assert day["energy"]["eaten"]["kcal"] == log["totals"]["kcal"]
    assert log["id"] in _shown(day)


# ───────────── user deletion and the migration ─────────────


def _meal_log(conn: Any, athlete: uuid.UUID, food: uuid.UUID, planned: bool) -> uuid.UUID:
    log_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO meal_log (id, athlete_id, date, planned_meal_id, status, slot, logged_at)"
            " VALUES (:id, :a, '2026-10-22', :p, :s, NULL, now())"
        ),
        {
            "id": log_id,
            "a": athlete,
            "p": uuid.uuid4() if planned else None,
            "s": "eaten" if planned else "extra",
        },
    )
    conn.execute(
        text(
            "INSERT INTO meal_log_item (id, meal_log_id, food_id, position, grams)"
            " VALUES (:id, :log, :food, 0, 100)"
        ),
        {"id": uuid.uuid4(), "log": log_id, "food": food},
    )
    return log_id


def test_deleting_a_user_with_meal_logs_is_never_blocked(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as conn:
            gone = _user(conn, "gone")
            stays = _user(conn, "stays")
            gone_food = _food(conn, gone)
            stays_food = _food(conn, stays)
            _meal_log(conn, gone, gone_food, planned=True)
            _meal_log(conn, gone, stays_food, planned=False)
            kept = _meal_log(conn, stays, stays_food, planned=False)
            other = _meal_log(conn, stays, gone_food, planned=True)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": gone})
        with engine.connect() as conn:

            def count(sql: str, **p: object) -> int:
                return int(conn.execute(text(sql), p).scalar_one())

            assert count("SELECT count(*) FROM meal_log WHERE athlete_id = :u", u=gone) == 0
            assert count("SELECT count(*) FROM meal_log_item WHERE food_id = :f", f=gone_food) == 0
            assert count("SELECT count(*) FROM meal_log WHERE athlete_id = :u", u=stays) == 2
            assert count("SELECT count(*) FROM meal_log_item WHERE meal_log_id = :l", l=kept) == 1
            # D70: the other athlete's item that used the deleted food goes (log row stays).
            assert count("SELECT count(*) FROM meal_log_item WHERE meal_log_id = :l", l=other) == 0
    finally:
        engine.dispose()


def test_partial_unique_index_allows_many_extras_but_one_log_per_planned_meal(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "a")
            food = _food(conn, athlete)
            _meal_log(conn, athlete, food, planned=False)
            _meal_log(conn, athlete, food, planned=False)
            planned = _meal_log(conn, athlete, food, planned=True)
            # The identity of a planned meal is (date, slot, slot index), not its per-version id.
            conn.execute(
                text("UPDATE meal_log SET slot = 'lunch', slot_index = 0 WHERE id = :i"),
                {"i": planned},
            )
        with (
            pytest.raises(IntegrityError, match="uq_meal_log_athlete_id_date_slot_slot_index"),
            engine.begin() as conn,
        ):
            conn.execute(
                text(
                    "INSERT INTO meal_log (id, athlete_id, date, planned_meal_id, status,"
                    " slot, slot_index, logged_at)"
                    " VALUES (:id, :a, '2026-10-22', :p, 'skipped', 'lunch', 0, now())"
                ),
                {"id": uuid.uuid4(), "a": athlete, "p": uuid.uuid4()},
            )
    finally:
        engine.dispose()


def test_migration_downgrades_and_upgrades_with_meal_log_data(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "a")
            food = _food(conn, athlete)
            _meal_log(conn, athlete, food, planned=True)
        down = _alembic(migrated_database_url, "downgrade", "f3b8d1a5c602")
        assert down.returncode == 0, down.stderr
        with engine.connect() as conn:
            tables = conn.execute(
                text(
                    "SELECT count(*) FROM pg_tables WHERE tablename IN ('meal_log','meal_log_item')"
                )
            ).scalar_one()
            assert tables == 0
            assert (
                conn.execute(
                    text("SELECT count(*) FROM food WHERE id = :f"), {"f": food}
                ).scalar_one()
                == 1
            )
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "f3b8d1a5c602"
            )
        up = _alembic(migrated_database_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        with engine.begin() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "c5e8a1d7b362"
            )
            _meal_log(conn, athlete, food, planned=True)
    finally:
        engine.dispose()


def test_today_is_the_users_local_day_for_the_future_check(migrated_database_url: str) -> None:
    """09:00 UTC Thursday is already Friday in Auckland: Friday is loggable there, Saturday not."""
    settings = make_settings(migrated_database_url)
    app = create_app(settings)
    app.state.clock = FakeClock(NOW.replace(hour=12))
    with TestClient(app) as client:
        api = Api(app=app, client=client, clock=app.state.clock)
        _seed_athlete(api)
        with Session(app.state.engine) as session:
            session.execute(text("UPDATE users SET timezone = 'Pacific/Auckland'"))
            session.commit()
        fri = (dt.date.fromisoformat(THU) + dt.timedelta(days=1)).isoformat()
        sat = (dt.date.fromisoformat(THU) + dt.timedelta(days=2)).isoformat()
        planned = _day(client, fri)["meals"][0]["planned_meal"]["id"]
        ok = client.post(
            f"{ME}/meal-logs", json={"date": fri, "planned_meal_id": planned, "status": "eaten"}
        )
        assert ok.status_code == 201, ok.text
        future = client.post(
            f"{ME}/meal-logs",
            json={
                "date": sat,
                "planned_meal_id": None,
                "status": "extra",
                "items": [{"food_id": ok.json()["meal_log"]["items"][0]["food"]["id"], "grams": 5}],
            },
        )
        assert future.status_code == 422 and future.json()["code"] == "date_in_future"


def test_accepting_a_suggestion_keeps_the_days_meal_logs(api: Api) -> None:
    """Reachable today: check off a meal, finish the workout, accept the suggestion (D65)."""
    from tests.integration.test_suggestions import MONDAY, _perform
    from tests.integration.test_training_log import _seed_athlete as _seed_training

    _seed_training(api)  # Monday strength + timed session (the #29/#85 fixture)
    with Session(api.app.state.engine) as session:
        plan = session.scalars(select(Plan).where(Plan.active.is_(True))).one()
        meals = list(
            session.scalars(
                select(Meal).where(Meal.owner_id.is_(None)).order_by(Meal.name).limit(3)
            )
        )
        for position, weekday in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun")):
            plan.meal_days.append(
                MealDay(
                    weekday=weekday,
                    position=position,
                    meals=[
                        PlannedMeal(slot=slot, position=i, meal_id=m.id, portion_factor=1.0)
                        for i, (slot, m) in enumerate(
                            zip(("breakfast", "lunch", "dinner"), meals, strict=True)
                        )
                    ],
                )
            )
        session.commit()
    api.clock.set(MONDAY)
    api.login()
    mon = "2026-10-19"
    planned = _day(api.client, mon)["meals"][0]["planned_meal"]["id"]
    logged = api.client.post(
        f"{ME}/meal-logs", json={"date": mon, "planned_meal_id": planned, "status": "eaten"}
    )
    assert logged.status_code == 201, logged.text
    sid = _perform(api, mon)
    items = api.client.get(f"{ME}/suggestions").json()["items"]
    (suggestion,) = [i for i in items if i["payload"]["source_session_id"] == sid]
    assert api.client.post(f"{BASE}/suggestions/{suggestion['id']}/accept").status_code == 200
    day = _day(api.client, mon)
    assert day["energy"]["eaten"]["kcal"] == logged.json()["meal_log"]["totals"]["kcal"]
    assert day["nutrition_completion"] == pytest.approx(1 / 3, abs=1e-3)
    assert logged.json()["meal_log"]["id"] in _shown(day)
