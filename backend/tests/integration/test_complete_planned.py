"""#223 Complete all as planned (F10.9, F10.10, D95) against real Postgres."""

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import PlannedExercise, SetLog, TrainingSession
from app.services import training_log
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem
from tests.integration.test_training_log import (
    BASE,
    _finish,
    _ids,
    _log,
    _seed_athlete,
    _session,
    _stranger,
)


@pytest.fixture
def athlete(api: Api) -> Api:
    _seed_athlete(api)
    return api


def _complete(api: Api, sid: str, client: Any = None) -> Any:
    return (client or api.client).post(f"{BASE}/sessions/{sid}/sets/complete-planned")


def _logs(api: Api) -> list[SetLog]:
    with Session(api.app.state.engine) as db:
        rows = list(db.scalars(select(SetLog).order_by(SetLog.exercise_id, SetLog.set_no)))
        db.expunge_all()
        return rows


def test_logs_every_unlogged_planned_set_as_planned_with_snapshots(athlete: Api) -> None:
    sid, ex, planned, timed = _ids(_session(athlete))
    response = _complete(athlete, sid)
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_schema(body, "Session")
    assert body["status"] == "in_progress"
    assert body["completion"] == 1.0
    logs = _logs(athlete)
    assert len(logs) == 4  # 3 strength sets + 1 timed set
    strength = [x for x in logs if str(x.exercise_id) == ex]
    assert [(x.set_no, x.reps, x.weight_kg, x.skipped) for x in strength] == [
        (n, 8, 50.0, False) for n in (1, 2, 3)
    ]
    assert all((x.target_reps, x.target_weight_kg) == (8, 50.0) for x in strength)
    assert all(str(x.planned_exercise_id) == planned for x in strength)
    (timed_log,) = [x for x in logs if str(x.exercise_id) == timed]
    assert (timed_log.seconds, timed_log.target_seconds, timed_log.reps) == (600, 600, None)
    # It does not finish the session.
    with Session(athlete.app.state.engine) as db:
        row = db.scalars(select(TrainingSession)).one()
        assert row.status == "in_progress" and row.started_at is not None
        assert row.finished_at is None


def test_is_idempotent(athlete: Api) -> None:
    sid, *_ = _ids(_session(athlete))
    first = _complete(athlete, sid).json()
    before = [(x.id, x.logged_at) for x in _logs(athlete)]
    second = _complete(athlete, sid)
    assert second.status_code == 200
    assert second.json() == first
    assert [(x.id, x.logged_at) for x in _logs(athlete)] == before


def test_leaves_edited_skipped_extra_and_no_target_sets_unchanged(athlete: Api) -> None:
    sid, ex, planned, timed = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, reps=5, weight_kg=40)
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=2, skipped=True)
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=4, reps=3, weight_kg=9)
    # A planned exercise without a target: strip the timed target from the plan.
    with Session(athlete.app.state.engine) as db:
        db.execute(
            update(PlannedExercise)
            .where(PlannedExercise.exercise_id == uuid.UUID(timed))
            .values(target_seconds=None)
        )
        db.commit()
    before = {
        (str(x.exercise_id), x.set_no): (x.reps, x.weight_kg, x.skipped) for x in _logs(athlete)
    }
    assert _complete(athlete, sid).status_code == 200
    after = {
        (str(x.exercise_id), x.set_no): (x.reps, x.weight_kg, x.skipped) for x in _logs(athlete)
    }
    for key, value in before.items():
        assert after[key] == value
    assert after[(ex, 3)] == (8, 50.0, False)  # the only new set
    assert len(after) == len(before) + 1  # nothing for the no-target timed set
    assert not any(k[0] == timed for k in after)


def test_a_plan_edit_after_logging_never_changes_completed_sets(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    _complete(athlete, sid)
    with Session(athlete.app.state.engine) as db:
        db.execute(
            update(PlannedExercise)
            .where(PlannedExercise.id == uuid.UUID(planned))
            .values(reps_min=20, reps_max=20, target_weight_kg=99)
        )
        db.commit()
    assert _complete(athlete, sid).status_code == 200
    strength = [x for x in _logs(athlete) if str(x.exercise_id) == ex]
    assert all((x.reps, x.target_reps, x.target_weight_kg) == (8, 8, 50.0) for x in strength)


def test_is_all_or_nothing(athlete: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    sid, *_ = _ids(_session(athlete))

    def boom(*_: Any) -> None:
        raise RuntimeError("fail after the sets were added")

    monkeypatch.setattr(training_log, "recompute", boom)
    problem(_complete(athlete, sid), 500, "internal_error")
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(SetLog)) == 0
        assert db.scalars(select(TrainingSession)).one().status == "planned"


def test_owner_only_with_the_codes_of_log_set(athlete: Api) -> None:
    sid, *_ = _ids(_session(athlete))
    stranger = _stranger(athlete)
    coach = _stranger(athlete, "coach@x.test", role="coach")
    for who in (stranger, coach):
        problem(_complete(athlete, sid, who), 403, "not_linked")
        problem(_complete(athlete, str(uuid.uuid4()), who), 403, "not_linked")
        assert _complete(athlete, "not-a-uuid", who).status_code == 400
    problem(_complete(athlete, str(uuid.uuid4())), 403, "not_linked")
    assert (
        athlete.new_client().post(f"{BASE}/sessions/{sid}/sets/complete-planned").status_code == 401
    )
    assert _logs(athlete) == []


def test_edit_window(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
    assert _finish(athlete, sid).status_code == 200
    # Inside the window the finished session can still be completed (status stays done).
    athlete.clock.set(dt.datetime(2026, 10, 23, 21, 59, tzinfo=dt.UTC))
    athlete.login()
    ok = _complete(athlete, sid)
    assert ok.status_code == 200 and ok.json()["status"] == "done"
    assert len(_logs(athlete)) == 4
    # Past it: 409 and nothing changes.
    athlete.clock.set(dt.datetime(2026, 10, 23, 22, 0, tzinfo=dt.UTC))
    athlete.login()
    problem(_complete(athlete, sid), 409, "edit_window_closed")
    assert len(_logs(athlete)) == 4


def _clear_weight(api: Api, planned: str) -> None:
    with Session(api.app.state.engine) as db:
        db.execute(
            update(PlannedExercise)
            .where(PlannedExercise.id == uuid.UUID(planned))
            .values(target_weight_kg=None)
        )
        db.commit()


def test_a_strength_set_without_a_planned_weight_is_not_logged_as_planned(athlete: Api) -> None:
    """D96: week-1 calibration plans have no weight; the athlete enters it."""
    sid, ex, planned, _ = _ids(_session(athlete))
    _clear_weight(athlete, planned)
    body = {"exercise_id": ex, "planned_exercise_id": planned, "set_no": 1, "as_planned": True}
    refused = athlete.client.post(f"{BASE}/sessions/{sid}/sets", json=body)
    assert "no target to copy" in problem(refused, 422, "invalid_set")["detail"]
    assert _logs(athlete) == []
    # Entering reps and weight works.
    entered = athlete.client.post(
        f"{BASE}/sessions/{sid}/sets",
        json={
            "exercise_id": ex,
            "planned_exercise_id": planned,
            "set_no": 1,
            "reps": 8,
            "weight_kg": 30,
        },
    )
    assert entered.status_code == 201, entered.text


def test_complete_planned_leaves_weightless_strength_sets_unlogged(athlete: Api) -> None:
    sid, ex, planned, timed = _ids(_session(athlete))
    _clear_weight(athlete, planned)
    assert _complete(athlete, sid).status_code == 200
    logs = _logs(athlete)
    assert [str(x.exercise_id) for x in logs] == [timed]  # only the timed set was logged
    assert not any(str(x.exercise_id) == ex for x in logs)
