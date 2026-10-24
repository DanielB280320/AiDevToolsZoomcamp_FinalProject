"""QA for #24 (PR #107): concurrency of version creation, the migration round trip,
telemetry privacy of `GET /athletes/{id}/plan` and the contract for an empty plan."""

import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Exercise, Plan, PlanChange, User
from app.seed import run_seed
from app.services.plans import NewPlannedExercise, NewTrainingDay, create_plan_version
from tests.conftest import JsonLogs, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, signup_body

BACKEND_DIR = Path(__file__).resolve().parents[2]
PLAN_REVISION = "c3b9f1a2d4e7"
BEFORE_PLAN_REVISION = "a7d3e5f10b64"
PLAN_TABLES = {"plan", "training_day", "planned_exercise", "plan_change"}


def _uid(engine: Engine, email: str = "ana@x.test") -> uuid.UUID:
    with Session(engine) as session:
        result: uuid.UUID = session.scalars(select(User.id).where(User.email == email)).one()
        return result


def test_concurrent_version_creation_gives_distinct_versions_and_one_active(api: Api) -> None:
    assert api.signup().status_code == 201
    engine = api.app.state.engine
    uid = _uid(engine)
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def create() -> None:
        try:
            with Session(engine) as session:
                barrier.wait(timeout=30)
                create_plan_version(
                    session, athlete_id=uid, author_id=uid, source="generated", days=[], now=NOW
                )
                session.commit()
        except BaseException as exc:  # surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=create) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    with Session(engine) as session:
        rows = session.execute(select(Plan.version, Plan.active).where(Plan.athlete_id == uid))
        rows_list = sorted(rows.all())
        assert [v for v, _ in rows_list] == [1, 2, 3, 4]
        assert [a for _, a in rows_list] == [False, False, False, True]
        assert len(session.scalars(select(PlanChange)).all()) == 4


def test_an_empty_plan_matches_the_contract(api: Api) -> None:
    assert api.signup().status_code == 201
    engine = api.app.state.engine
    uid = _uid(engine)
    with Session(engine) as session:
        create_plan_version(
            session, athlete_id=uid, author_id=uid, source="custom", days=[], now=NOW
        )
        session.commit()
    response = api.client.get("/api/v1/athletes/me/plan")
    assert response.status_code == 200, response.text
    assert_matches_schema(response.json(), "Plan")
    assert response.json()["training_days"] == []


def test_get_plan_puts_no_plan_content_in_logs_or_spans(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, span_exporter, _ = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/signup", json=signup_body()).status_code == 201
        engine = app.state.engine
        with Session(engine) as session:
            run_seed(session)
        uid = _uid(engine)
        with Session(engine) as session:
            exercise = session.scalars(
                select(Exercise).where(Exercise.owner_id.is_(None), Exercise.type == "strength")
            ).first()
            assert exercise is not None
            exercise_name = exercise.name
            day = NewTrainingDay(
                "tue",
                "Zebraday",
                [NewPlannedExercise(exercise.id, 3, 90, "linear", 2.5, 5, 5, 87.25)],
            )
            create_plan_version(
                session, athlete_id=uid, author_id=uid, source="generated", days=[day], now=NOW
            )
            session.commit()
        body = client.get(f"/api/v1/athletes/{uid}/plan").json()
        assert body["training_days"][0]["name"] == "Zebraday"

    spans = " ".join(str(s.to_json()) for s in span_exporter.get_finished_spans())
    for secret in ("Zebraday", exercise_name, "87.25", "ana@x.test", str(uid)):
        assert secret not in json_logs.text, secret
        assert secret not in spans, secret


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


def test_plan_migration_upgrades_downgrades_and_upgrades_again(fresh_database_url: str) -> None:
    up = _alembic(fresh_database_url, "upgrade", BEFORE_PLAN_REVISION)
    assert up.returncode == 0, up.stderr
    before = _schema(fresh_database_url)
    assert not PLAN_TABLES & before.keys()

    up = _alembic(fresh_database_url, "upgrade", PLAN_REVISION)
    assert up.returncode == 0, up.stderr
    after = _schema(fresh_database_url)
    assert after.keys() >= PLAN_TABLES
    # Expand-only: every earlier table keeps exactly its columns.
    assert {t: after[t] for t in before} == before

    down = _alembic(fresh_database_url, "downgrade", BEFORE_PLAN_REVISION)
    assert down.returncode == 0, down.stderr
    assert _schema(fresh_database_url) == before

    again = _alembic(fresh_database_url, "upgrade", "head")
    assert again.returncode == 0, again.stderr
    assert _schema(fresh_database_url).keys() >= PLAN_TABLES
