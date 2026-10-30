# ruff: noqa: S608  (table/column names are constants in this test)
"""#148 / D69: foreign keys to `users.id` (plan.created_by, plan_change.author_id,
training_day.edited_by, meal_day.edited_by, suggestion.decided_by) must not block user deletion
(F18.2). Rows are inserted directly; the delete endpoint is #50."""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.migrations import BACKEND_DIR


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[Engine]:
    built = create_engine(migrated_database_url)
    yield built
    built.dispose()


def _user(conn: Connection, role: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role, birth_date, units,"
            " timezone, disclaimer_accepted_at, created_at, updated_at) VALUES (:id, :email, 'x',"
            " 'T', :role, '1990-01-01', 'metric', 'UTC', now(), now(), now())"
        ),
        {"id": user_id, "email": f"u-{user_id}@example.com", "role": role},
    )
    return user_id


def _plan(
    conn: Connection, athlete: uuid.UUID, author: uuid.UUID, editor: uuid.UUID
) -> dict[str, uuid.UUID]:
    ids = {k: uuid.uuid4() for k in ("plan", "training_day", "meal_day", "change", "suggestion")}
    conn.execute(
        text(
            "INSERT INTO plan (id, athlete_id, version, source, active, revision, created_by,"
            " created_at, updated_at) VALUES (:id, :a, 1, 'custom', true, 0, :by, now(), now())"
        ),
        {"id": ids["plan"], "a": athlete, "by": author},
    )
    conn.execute(
        text(
            'INSERT INTO training_day (id, plan_id, weekday, name, "order", edited_by)'
            " VALUES (:id, :p, 'mon', 'Push', 0, :e)"
        ),
        {"id": ids["training_day"], "p": ids["plan"], "e": editor},
    )
    conn.execute(
        text(
            'INSERT INTO meal_day (id, plan_id, weekday, "order", edited_by)'
            " VALUES (:id, :p, 'mon', 0, :e)"
        ),
        {"id": ids["meal_day"], "p": ids["plan"], "e": editor},
    )
    conn.execute(
        text(
            "INSERT INTO plan_change (id, plan_id, author_id, change, created_at)"
            " VALUES (:id, :p, :by, '{}', now())"
        ),
        {"id": ids["change"], "p": ids["plan"], "by": author},
    )
    conn.execute(
        text(
            "INSERT INTO suggestion (id, athlete_id, kind, status, rule, reason, inputs, payload,"
            " created_at, decided_by, decided_at) VALUES (:id, :a, 'progression', 'accepted',"
            " 'linear', 'r', '{}', '{}', now(), :e, now())"
        ),
        {"id": ids["suggestion"], "a": athlete, "e": editor},
    )
    return ids


def _count(conn: Connection, sql: str, **params: object) -> int:
    return int(conn.execute(text(sql), params).scalar_one())


TABLES = ("plan", "plan_change", "training_day", "meal_day", "suggestion")


def test_deleting_an_onboarded_athlete_removes_all_their_rows(engine: Engine) -> None:
    with engine.begin() as conn:
        athlete = _user(conn, "athlete")
        bystander = _user(conn, "athlete")
        _plan(conn, athlete, athlete, athlete)
        other = _plan(conn, bystander, bystander, bystander)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": athlete})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=athlete) == 0
        for table in TABLES:
            assert _count(conn, f"SELECT count(*) FROM {table}") == (1), (
                f"{table} rows of the deleted athlete remain"
            )
        assert _count(conn, "SELECT count(*) FROM plan WHERE id = :p", p=other["plan"]) == 1


def test_deleting_a_coach_keeps_the_athletes_data_and_clears_the_references(
    engine: Engine,
) -> None:
    with engine.begin() as conn:
        athlete = _user(conn, "athlete")
        coach = _user(conn, "coach")
        ids = _plan(conn, athlete, coach, coach)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": coach})
    with engine.connect() as conn:
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=coach) == 0
        assert _count(conn, "SELECT count(*) FROM users WHERE id = :u", u=athlete) == 1
        for table in TABLES:
            assert _count(conn, f"SELECT count(*) FROM {table}") == 1
        checks = {
            "plan": "created_by",
            "plan_change": "author_id",
            "training_day": "edited_by",
            "meal_day": "edited_by",
            "suggestion": "decided_by",
        }
        for table, column in checks.items():
            assert _count(conn, f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL") == 0
        assert _count(conn, "SELECT count(*) FROM plan WHERE id = :p", p=ids["plan"]) == 1


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_migration_downgrades_and_upgrades_again_with_existing_data(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "athlete")
            coach = _user(conn, "coach")
            _plan(conn, athlete, coach, coach)
            other_athlete = _user(conn, "athlete")
            gone = _user(conn, "coach")
            _plan(conn, other_athlete, gone, gone)
            conn.execute(text("DELETE FROM users WHERE id = :g"), {"g": gone})
        down = _alembic(migrated_database_url, "downgrade", "-1")
        assert down.returncode == 0, down.stderr
        with engine.connect() as conn:
            assert _count(conn, "SELECT count(*) FROM plan WHERE created_by IS NULL") == 0
            assert _count(conn, "SELECT count(*) FROM plan") == 2
        up = _alembic(migrated_database_url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": coach})
        with engine.connect() as conn:
            assert _count(conn, "SELECT count(*) FROM plan") == 2
    finally:
        engine.dispose()
