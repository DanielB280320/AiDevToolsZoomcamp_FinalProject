"""D110 (CLAUDE.md rule 8): the data migration recalculates every stored `session.completion`
with the per-set formula, gives the same ratio as the engine, leaves sessions without a stored
completion alone, and its downgrade restores the previous formula's value."""

import uuid

import pytest
from sqlalchemy import Connection, create_engine, text

from app.engines.session_completion import PlannedSetResult, completion
from tests.integration.test_session_import_migration import _plan_and_day
from tests.integration.test_user_delete_food_cascade import _alembic, _user

PREVIOUS_HEAD = "e2a7c9d1b346"
R = PlannedSetResult


def _exercise(conn: Connection, kind: str) -> uuid.UUID:
    exercise = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO exercise (id, name, muscle_group, equipment, type, met, increment_kg,"
            " region) VALUES (:id, :name, 'chest', 'none', :kind, 3, 0, 'upper')"
        ),
        {"id": exercise, "name": f"E {exercise}", "kind": kind},
    )
    return exercise


def _planned(conn: Connection, day: uuid.UUID, kind: str, sets: int, target: int) -> uuid.UUID:
    exercise = _exercise(conn, kind)
    timed = kind == "timed"
    conn.execute(
        text(
            'INSERT INTO planned_exercise (id, training_day_id, exercise_id, "order", sets,'
            " reps_min, target_seconds, rule, increment_kg) VALUES (:id, :d, :e, 1, :sets,"
            " :reps, :seconds, 'manual', 0)"
        ),
        {
            "id": uuid.uuid4(),
            "d": day,
            "e": exercise,
            "sets": sets,
            "reps": None if timed else target,
            "seconds": target if timed else None,
        },
    )
    return exercise


def _session(
    conn: Connection,
    athlete: uuid.UUID,
    plan: uuid.UUID,
    day: uuid.UUID,
    date: str,
    stored: float | None,
) -> uuid.UUID:
    session = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO session (id, athlete_id, plan_id, training_day_id, date, status,"
            " completion, created_at) VALUES (:id, :a, :p, :t, :d, 'done', :c, now())"
        ),
        {"id": session, "a": athlete, "p": plan, "t": day, "d": date, "c": stored},
    )
    return session


def _log(
    conn: Connection, session: uuid.UUID, exercise: uuid.UUID, set_no: int, **values: object
) -> None:
    blank = {"target_reps": None, "target_seconds": None, "reps": None, "seconds": None}
    row = {**blank, "skipped": False, **values}
    conn.execute(
        text(
            "INSERT INTO set_log (id, session_id, exercise_id, set_no, skipped, target_reps,"
            " target_seconds, reps, seconds, logged_at) VALUES (:id, :s, :e, :n, :skipped,"
            " :target_reps, :target_seconds, :reps, :seconds, now())"
        ),
        {"id": uuid.uuid4(), "s": session, "e": exercise, "n": set_no, **row},
    )


def _completions(conn: Connection) -> dict[uuid.UUID, float | None]:
    rows = conn.execute(text("SELECT id, completion FROM session")).all()
    return {row[0]: None if row[1] is None else float(row[1]) for row in rows}


def test_stored_completion_is_recomputed_per_set_and_the_downgrade_restores_it(
    fresh_database_url: str,
) -> None:
    up = _alembic(fresh_database_url, "upgrade", PREVIOUS_HEAD)
    assert up.returncode == 0, up.stderr
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "a")
            plan, day = _plan_and_day(conn, athlete)
            # The owner's session: 5x6, 5x6, 4 x 3x10 and one 600 s set.
            squat = _planned(conn, day, "strength", 5, 6)
            _planned(conn, day, "strength", 5, 6)
            for _ in range(4):
                _planned(conn, day, "bodyweight", 3, 10)
            rope = _planned(conn, day, "timed", 1, 600)

            # 1 of 22 strength sets and the timed set: 606 / 780 before, 2 of 23 sets now.
            owner = _session(conn, athlete, plan, day, "2026-11-09", 0.7769)
            _log(conn, owner, squat, 1, target_reps=6, reps=6)
            _log(conn, owner, rope, 1, target_seconds=600, seconds=600)

            # Snapshot target differs from the plan, a partial set, a skipped set, extra reps and
            # an extra (unplanned) set that must not count.
            mixed = _session(conn, athlete, plan, day, "2026-11-10", 0.5)
            _log(conn, mixed, squat, 1, target_reps=8, reps=4)
            _log(conn, mixed, squat, 2, target_reps=6, reps=12)
            _log(conn, mixed, squat, 3, skipped=True, target_reps=6)
            _log(conn, mixed, squat, 6, target_reps=6, reps=6)
            _log(conn, mixed, rope, 1, target_seconds=600, seconds=300)

            untouched = _session(conn, athlete, plan, day, "2026-11-11", None)

        head = _alembic(fresh_database_url, "upgrade", "head")
        assert head.returncode == 0, head.stderr

        rest = [R(6, None)] * 5 + [R(10, None)] * 12
        expected_owner = completion([R(6, 6)] + [R(6, None)] * 4 + rest + [R(600, 600)]).ratio
        expected_mixed = completion(
            [R(8, 4), R(6, 12), R(6, 0), R(6, None), R(6, None), *rest, R(600, 300)]
        ).ratio
        assert expected_owner == 0.087
        with engine.begin() as conn:
            after = _completions(conn)
        assert after[owner] == pytest.approx(expected_owner, abs=1e-4)
        assert after[mixed] == pytest.approx(expected_mixed, abs=1e-4)
        assert after[untouched] is None

        down = _alembic(fresh_database_url, "downgrade", PREVIOUS_HEAD)
        assert down.returncode == 0, down.stderr
        with engine.begin() as conn:
            before = _completions(conn)
        assert before[owner] == pytest.approx(606 / 780, abs=1e-4)
        assert before[untouched] is None
        again = _alembic(fresh_database_url, "upgrade", "head")
        assert again.returncode == 0, again.stderr
    finally:
        engine.dispose()
