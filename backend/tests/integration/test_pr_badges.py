"""#56 Personal record badges (F15, D88): `is_pr` on the exercise block of GET /sessions/{id} and
the finishSession response, computed on read with the F15 exercise-chart ranking."""

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import SetLog
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem, signup_body
from tests.integration.chart_data import Seeded, add_session, seed_plan
from tests.integration.test_training_log import _finish, _ids, _log, _seed_athlete, _session

API = "/api/v1"


@pytest.fixture
def seeded(api: Api) -> tuple[Api, Seeded]:
    return api, seed_plan(api)


def _add(api: Api, seed: Seeded, day: dt.date, sets: list[Any], **kw: Any) -> str:
    with Session(api.app.state.engine) as db:
        row = add_session(db, seed, day, sets=sets, **kw)
        db.commit()
        return str(row.id)


def _flag(api: Api, sid: str, seed: Seeded) -> bool:
    r = api.client.get(f"{API}/sessions/{sid}")
    assert r.status_code == 200, r.text
    assert_matches_schema(r.json(), "Session")
    block = next(e for e in r.json()["exercises"] if e["exercise"]["id"] == str(seed.strength_id))
    flag: bool = block["is_pr"]
    return flag


def test_is_pr_agrees_with_the_exercise_chart_for_the_same_history(
    seeded: tuple[Api, Seeded],
) -> None:
    api, seed = seeded
    days = [dt.date(2026, 9, 3), dt.date(2026, 10, 1), dt.date(2026, 10, 8), dt.date(2026, 10, 15)]
    light, heavy = [(8, 50, 8, 50)], [(8, 52.5, 8, 52.5)]
    plans: list[list[Any]] = [light, heavy, light, heavy]
    sids = {d: _add(api, seed, d, s) for d, s in zip(days, plans, strict=True)}
    # lighter on the 8th, a tie on the 15th: only the first two are records
    chart = api.client.get(f"{API}/athletes/me/charts/exercise/{seed.strength_id}?weeks=26").json()
    by_date = {p["date"]: p["is_pr"] for p in chart["points"]}
    assert list(by_date.values()) == [True, True, False, False]
    for d in days:
        assert _flag(api, sids[d], seed) is by_date[d.isoformat()], d


def test_first_set_is_pr_skipped_and_ties_are_not(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    first = _add(api, seed, dt.date(2026, 10, 1), [(8, 50, 8, 50)])
    tie = _add(api, seed, dt.date(2026, 10, 8), [(8, 50, 8, 50)])
    skipped_only = _add(api, seed, dt.date(2026, 10, 12), [(8, 99, 8, 50)], skipped_sets=(1,))
    assert _flag(api, first, seed) is True
    assert _flag(api, tie, seed) is False
    assert _flag(api, skipped_only, seed) is False


def test_is_pr_is_computed_on_read_after_delete_or_edit(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    base = _add(api, seed, dt.date(2026, 10, 1), [(8, 50, 8, 50)])
    record = _add(api, seed, dt.date(2026, 10, 8), [(8, 60, 8, 60)])
    assert _flag(api, record, seed) is True
    with Session(api.app.state.engine) as db:  # the earlier best is raised (an edit)
        log = db.scalars(select(SetLog).where(SetLog.session_id == base)).one()
        log.weight_kg = 70
        db.commit()
    assert _flag(api, record, seed) is False
    with Session(api.app.state.engine) as db:  # the set is deleted (outside the edit window here)
        db.execute(delete(SetLog).where(SetLog.session_id == base))
        db.commit()
    assert _flag(api, record, seed) is True  # the set that was ahead is gone
    assert _flag(api, base, seed) is False  # nothing logged any more


def test_finish_session_response_carries_is_pr(api: Api) -> None:
    _seed_athlete(api)
    sid, ex, planned, _ = _ids(_session(api))
    _log(api, sid, set_no=1, reps=8, weight_kg=50, exercise_id=ex, planned_exercise_id=planned)
    finished = _finish(api, sid)
    assert finished.status_code == 200, finished.text
    first, other = finished.json()["session"]["exercises"]
    assert first["is_pr"] is True  # first-ever logged set
    assert other["is_pr"] is False  # nothing logged


def test_timed_exercise_ranks_by_duration(api: Api) -> None:
    _seed_athlete(api)
    sid, _, _, timed = _ids(_session(api))
    _log(api, sid, set_no=1, exercise_id=timed, seconds=600)
    body = _finish(api, sid).json()["session"]
    assert next(e for e in body["exercises"] if e["exercise"]["id"] == timed)["is_pr"] is True


def test_stranger_cannot_read_the_flag(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    sid = _add(api, seed, dt.date(2026, 10, 1), [(8, 50, 8, 50)])
    stranger = api.new_client()
    r = stranger.post(f"{API}/auth/signup", json=signup_body(email="bo@x.test"))
    assert r.status_code == 201
    problem(stranger.get(f"{API}/sessions/{sid}"), 403, "not_linked")
