"""QA for #29 (PR #123): migration round trip, telemetry privacy of the logging endpoints,
and the kcal recompute on an in-window edit after a later weigh-in."""

import datetime as dt
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Exercise, User
from tests.conftest import Captured, JsonLogs, captured_telemetry, make_settings
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem
from tests.integration.test_training_log import (
    BASE,
    THU,
    _expected_kcal_exact,
    _finish,
    _ids,
    _log,
    _seed_athlete,
    _session,
    _timed,
    _weight_now,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
LOG_REVISION = "e6b1f3a9c2d8"
BEFORE_LOG_REVISION = "d5e8a1b3c7f9"
LOG_TABLES = {"set_log", "extra_activity"}


@pytest.fixture
def athlete(api: Api) -> Api:
    _seed_athlete(api)
    return api


# ───────────── migration: expand-only round trip ─────────────


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _schema(url: str) -> dict[str, set[str]]:
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        return {
            t: {c["name"] for c in insp.get_columns(t)}
            for t in insp.get_table_names()
            if t != "alembic_version"
        }
    finally:
        engine.dispose()


def test_logging_migration_upgrades_downgrades_and_upgrades_again(fresh_database_url: str) -> None:
    up = _alembic(fresh_database_url, "upgrade", BEFORE_LOG_REVISION)
    assert up.returncode == 0, up.stderr
    before = _schema(fresh_database_url)
    assert not LOG_TABLES & before.keys()

    up = _alembic(fresh_database_url, "upgrade", LOG_REVISION)
    assert up.returncode == 0, up.stderr
    after = _schema(fresh_database_url)
    assert after.keys() >= LOG_TABLES
    # Expand-only: every earlier table keeps exactly its columns, so the previous image still runs.
    assert {t: after[t] for t in before} == before
    assert {"target_reps", "target_weight_kg", "target_seconds"} <= after["set_log"]

    down = _alembic(fresh_database_url, "downgrade", BEFORE_LOG_REVISION)
    assert down.returncode == 0, down.stderr
    assert _schema(fresh_database_url) == before

    again = _alembic(fresh_database_url, "upgrade", "head")
    assert again.returncode == 0, again.stderr
    assert _schema(fresh_database_url).keys() >= LOG_TABLES


# ───────────── telemetry privacy (rule 6) ─────────────


def test_logging_endpoints_keep_health_data_out_of_logs_spans_and_metrics(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, spans, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    captured = Captured(app, telemetry, spans, reader)
    with TestClient(app) as client:
        api = Api(app=app, client=client, clock=app.state.clock)
        _seed_athlete(api)
        sid, ex, planned, timed = _ids(_session(api))
        # Distinctive values that must never show up in telemetry.
        assert (
            _log(
                api,
                sid,
                exercise_id=ex,
                planned_exercise_id=planned,
                set_no=1,
                reps=17,
                weight_kg=123.75,
            ).status_code
            == 201
        )
        timed_set = _log(api, sid, exercise_id=timed, set_no=1, seconds=1234, distance_m=4321.5)
        assert timed_set.status_code == 201
        # An invalid set (error path) must not echo values either.
        problem(
            _log(api, sid, exercise_id=ex, planned_exercise_id=planned, set_no=2, seconds=9876),
            422,
            "invalid_set",
        )
        assert _finish(api, sid).status_code == 200
        activity = client.post(
            f"{BASE}/athletes/me/activities",
            json={"date": THU, "exercise_id": _timed(api), "minutes": 77},
        )
        assert activity.status_code == 201
        with Session(app.state.engine) as db:
            uid = db.scalars(select(User.id)).one()
            names = [db.get(Exercise, uuid.UUID(e)).name for e in (ex, timed)]  # type: ignore[union-attr]

    exported = " ".join(str(s.to_json()) for s in captured.span_exporter.get_finished_spans())
    for secret in ("123.75", "4321.5", "1234", "9876", "ana@x.test", str(uid), *names):
        assert secret not in json_logs.text, secret
        assert secret not in exported, secret
    for name in ("fitwise_sets_logged_total", "fitwise_workouts_finished_total"):
        points = captured.metric_points(name)
        assert points, name
        assert all(not dict(p.attributes or {}) for p in points), name


# ───────────── F10.3 + F13.2: in-window edit after a later weigh-in ─────────────


def test_edit_in_window_recomputes_kcal_with_the_weight_on_the_session_date(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
    finished = _finish(athlete, sid).json()["session"]
    # Next day: a new weigh-in, then an extra set inside the edit window.
    athlete.clock.set(dt.datetime(2026, 10, 23, 12, 0, tzinfo=dt.UTC))
    athlete.login()
    _weight_now(athlete, 120.0, dt.date(2026, 10, 23))
    assert (
        _log(
            athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=2, as_planned=True
        ).status_code
        == 201
    )
    after = athlete.client.get(f"{BASE}/sessions/{sid}").json()
    expected = _expected_kcal_exact(athlete, ex, 80.0, 2 * (90 + 45) / 60)
    assert after["kcal"] == int(expected + 0.5)  # 80 kg (on/before Thursday), not 120 kg
    assert after["kcal"] > finished["kcal"]
    assert after["completion"] > finished["completion"]
