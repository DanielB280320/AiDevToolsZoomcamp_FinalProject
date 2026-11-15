"""D110 migration edge cases (QA): the stored completion the migration writes must equal what
`training_log.recompute` writes for the same rows, and plan-less (imported) sessions are left
alone. Covers the same exercise planned twice in one day, logs beyond the planned set count, a
logged set without a target snapshot, a set without a positive planned target, and a ratio that
lands exactly on a 5 in the fifth decimal."""

import uuid

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session

from app.models.session import TrainingSession
from app.services import training_log
from tests.integration.test_session_completion_migration import _exercise, _log, _session
from tests.integration.test_session_import_migration import _plan_and_day
from tests.integration.test_user_delete_food_cascade import _alembic, _user

PREVIOUS_HEAD = "e2a7c9d1b346"


def _plan_row(
    conn: Connection,
    day: uuid.UUID,
    exercise: uuid.UUID,
    sets: int,
    reps: int | None = None,
    seconds: int | None = None,
    order: int = 1,
) -> None:
    conn.execute(
        text(
            'INSERT INTO planned_exercise (id, training_day_id, exercise_id, "order", sets,'
            " reps_min, target_seconds, rule, increment_kg) VALUES (:id, :d, :e, :o, :sets,"
            " :reps, :seconds, 'manual', 0)"
        ),
        {
            "id": uuid.uuid4(),
            "d": day,
            "e": exercise,
            "o": order,
            "sets": sets,
            "reps": reps,
            "seconds": seconds,
        },
    )


def _stored(conn: Connection, session: uuid.UUID) -> float | None:
    value = conn.execute(
        text("SELECT completion FROM session WHERE id = :id"), {"id": session}
    ).scalar_one()
    return None if value is None else float(value)


def _recomputed(url: str, session: uuid.UUID) -> float | None:
    """What the application writes for the session (not committed)."""
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            row = db.get(TrainingSession, session)
            assert row is not None
            training_log.recompute(db, row)
            value = row.completion
            db.rollback()
        return None if value is None else float(value)
    finally:
        engine.dispose()


def _upgrade_from_previous(url: str) -> None:
    up = _alembic(url, "upgrade", PREVIOUS_HEAD)
    assert up.returncode == 0, up.stderr


def _upgrade_head(url: str) -> None:
    head = _alembic(url, "upgrade", "head")
    assert head.returncode == 0, head.stderr


def test_migration_matches_recompute_on_edge_cases(fresh_database_url: str) -> None:
    _upgrade_from_previous(fresh_database_url)
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "qa")
            plan, day = _plan_and_day(conn, athlete)
            press = _exercise(conn, "strength")
            plank = _exercise(conn, "timed")
            open_ended = _exercise(conn, "strength")
            # The same exercise planned twice in one training day (3x8, then 2x5).
            _plan_row(conn, day, press, 3, reps=8, order=1)
            _plan_row(conn, day, press, 2, reps=5, order=2)
            _plan_row(conn, day, plank, 1, seconds=60, order=3)
            # No positive planned target: never counted.
            _plan_row(conn, day, open_ended, 2, reps=None, order=4)

            twice = _session(conn, athlete, plan, day, "2026-11-02", 0.4)
            _log(conn, twice, press, 1, target_reps=8, reps=8)
            _log(conn, twice, press, 2, target_reps=8, reps=4)
            _log(conn, twice, press, 3, target_reps=8, reps=8)
            _log(conn, twice, press, 7, target_reps=8, reps=8)  # beyond every planned count
            _log(conn, twice, plank, 1, target_seconds=60, seconds=90)

            no_snapshot = _session(conn, athlete, plan, day, "2026-11-03", 0.2)
            _log(conn, no_snapshot, press, 1, reps=8)  # logged without a target snapshot
            _log(conn, no_snapshot, plank, 1, skipped=True, target_seconds=60)
            _log(conn, no_snapshot, open_ended, 1, reps=10)

            imported = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO session (id, athlete_id, plan_id, training_day_id, date, status,"
                    " completion, imported, created_at) VALUES (:id, :a, NULL, NULL,"
                    " '2026-10-01', 'done', 0.5, true, now())"
                ),
                {"id": imported, "a": athlete},
            )

        _upgrade_head(fresh_database_url)

        with engine.begin() as conn:
            stored = {s: _stored(conn, s) for s in (twice, no_snapshot, imported)}
        for session in (twice, no_snapshot):
            assert stored[session] is not None
            assert 0 <= stored[session] <= 1  # type: ignore[operator]
            assert stored[session] == pytest.approx(
                _recomputed(fresh_database_url, session), abs=1e-9
            )
        assert stored[imported] == 0.5  # plan-less sessions are not touched
    finally:
        engine.dispose()


def test_migration_rounds_a_half_like_the_application(fresh_database_url: str) -> None:
    """1 of 32 planned sets done is exactly 0.03125: the migration must store what the
    application stores for the same session, or the value flips on the next edit."""
    _upgrade_from_previous(fresh_database_url)
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "qa")
            plan, day = _plan_and_day(conn, athlete)
            first = None
            for order in range(1, 5):
                exercise = _exercise(conn, "strength")
                first = first or exercise
                _plan_row(conn, day, exercise, 8, reps=10, order=order)
            assert first is not None
            session = _session(conn, athlete, plan, day, "2026-11-04", 0.01)
            _log(conn, session, first, 1, target_reps=10, reps=10)

        _upgrade_head(fresh_database_url)

        with engine.begin() as conn:
            stored = _stored(conn, session)
        assert stored == pytest.approx(_recomputed(fresh_database_url, session), abs=1e-9)
    finally:
        engine.dispose()


def test_migration_rounds_a_tie_from_non_terminating_shares_like_the_application(
    fresh_database_url: str,
) -> None:
    """Sets done 1/3 and 2/3 of target plus 30 unlogged sets: (1/3 + 2/3) / 32 = 1/32 = 0.03125
    exactly. The shares do not terminate in decimal, so the migration must round the tie
    up (not miss it through representation error) to match the application's 0.0313."""
    _upgrade_from_previous(fresh_database_url)
    engine = create_engine(fresh_database_url)
    try:
        with engine.begin() as conn:
            athlete = _user(conn, "qa")
            plan, day = _plan_and_day(conn, athlete)
            exercise = _exercise(conn, "strength")
            _plan_row(conn, day, exercise, 8, reps=10, order=1)
            for order in range(2, 5):
                _plan_row(conn, day, _exercise(conn, "strength"), 8, reps=10, order=order)
            session = _session(conn, athlete, plan, day, "2026-11-05", 0.01)
            _log(conn, session, exercise, 1, target_reps=3, reps=1)
            _log(conn, session, exercise, 2, target_reps=3, reps=2)

        _upgrade_head(fresh_database_url)

        with engine.begin() as conn:
            stored = _stored(conn, session)
        recomputed = _recomputed(fresh_database_url, session)
        assert recomputed == pytest.approx(0.0313, abs=1e-9)
        assert stored == pytest.approx(0.0313, abs=1e-9)
        assert stored == pytest.approx(recomputed, abs=1e-9)
    finally:
        engine.dispose()
