"""#29 Training logging API against real Postgres: set upsert (F10.1), completion (F10.2), finish
and the edit window (F10.3), moved sessions (F9.2), kcal, extra activities (F10.4), snapshots,
authorization and the key-journey counters."""

import datetime as dt
import math
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import (
    BodyMetric,
    Exercise,
    ExtraActivity,
    PlannedExercise,
    SetLog,
    TrainingSession,
    User,
)
from app.seed import run_seed
from app.services.plans import NewPlannedExercise, NewTrainingDay, create_plan_version
from tests.conftest import Captured, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem, signup_body

# NOW is Thursday 2026-10-22 09:00 UTC (11:00 in Europe/Madrid). Week: Mon 19 .. Sun 25.
THU = "2026-10-22"
FRI = "2026-10-23"
PLAN_CREATED = NOW - dt.timedelta(days=60)
BASE = "/api/v1"


def _seed_athlete(
    api: Api, email: str = "ana@x.test", weekdays: tuple[str, ...] = ("mon", "thu", "fri")
) -> None:
    assert api.signup(email=email).status_code == 201
    with Session(api.app.state.engine) as session:
        run_seed(session)
        uid = session.scalars(select(User.id).where(User.email == email)).one()
        strength = session.scalars(
            select(Exercise).where(Exercise.owner_id.is_(None), Exercise.type == "strength")
        ).first()
        timed = session.scalars(
            select(Exercise).where(Exercise.owner_id.is_(None), Exercise.type == "timed")
        ).first()
        assert strength is not None and timed is not None
        create_plan_version(
            session,
            athlete_id=uid,
            author_id=uid,
            source="generated",
            days=[
                NewTrainingDay(
                    w,
                    f"Day {w}",
                    [
                        NewPlannedExercise(
                            strength.id,
                            3,
                            90,
                            "linear",
                            2.5,
                            reps_min=8,
                            reps_max=8,
                            target_weight_kg=50.0,
                        ),
                        NewPlannedExercise(timed.id, 1, 60, "linear", 0, target_seconds=600),
                    ],
                )
                for w in weekdays
            ],
            now=PLAN_CREATED,
        )
        session.add(
            BodyMetric(user_id=uid, date=dt.date(2026, 9, 1), weight_kg=80.0, created_at=NOW)
        )
        session.commit()


@pytest.fixture
def athlete(api: Api) -> Api:
    _seed_athlete(api)
    return api


def _session(api: Api, day: str = THU, client: Any = None) -> dict[str, Any]:
    response = (client or api.client).get(f"{BASE}/athletes/me/days/{day}")
    assert response.status_code == 200, response.text
    session: dict[str, Any] = response.json()["session"]
    return session


def _ids(session: dict[str, Any]) -> tuple[str, str, str, str]:
    """(session id, strength exercise id, planned strength id, timed exercise id)."""
    strength, timed = session["exercises"]
    return (
        session["id"],
        strength["exercise"]["id"],
        strength["planned_exercise_id"],
        timed["exercise"]["id"],
    )


def _log(api: Api, sid: str, client: Any = None, **body: Any) -> Any:
    return (client or api.client).post(f"{BASE}/sessions/{sid}/sets", json=body)


def _finish(api: Api, sid: str, client: Any = None, body: Any = None) -> Any:
    return (client or api.client).post(f"{BASE}/sessions/{sid}/finish", json=body)


def _weight_now(api: Api, kg: float, day: dt.date) -> None:
    with Session(api.app.state.engine) as session:
        uid = session.scalars(select(User.id)).first()
        session.add(BodyMetric(user_id=uid, date=day, weight_kg=kg, created_at=NOW))
        session.commit()


def _expected_kcal(api: Api, exercise_id: str, weight: float, minutes: float) -> int:
    with Session(api.app.state.engine) as session:
        met = session.get(Exercise, uuid.UUID(exercise_id)).met  # type: ignore[union-attr]
    return math.floor(met * 3.5 * weight / 200 * minutes + 0.5)


def _stranger(api: Api, email: str = "bo@x.test", role: str = "athlete") -> TestClient:
    client = api.new_client()
    response = client.post(f"{BASE}/auth/signup", json=signup_body(email=email, role=role))
    assert response.status_code == 201
    return client


# ───────────── F10.1 idempotent set logging ─────────────


def test_logging_a_set_twice_replaces_it_and_never_duplicates(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    first = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, reps=8, weight_kg=50
    )
    assert first.status_code == 201, first.text
    assert_matches_schema(first.json(), "SetLog")
    retry = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, reps=8, weight_kg=50
    )
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    fix = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, reps=6, weight_kg=45
    )
    assert fix.status_code == 200
    assert (fix.json()["reps"], fix.json()["weight_kg"]) == (6, 45)
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(SetLog)) == 1


def test_concurrent_identical_requests_create_one_set(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    body = {"exercise_id": ex, "planned_exercise_id": planned, "set_no": 1, "as_planned": True}

    def call(_: int) -> int:
        client = TestClient(athlete.app)
        client.cookies.update(athlete.client.cookies)
        return client.post(f"{BASE}/sessions/{sid}/sets", json=body).status_code

    with ThreadPoolExecutor(6) as pool:
        codes = sorted(pool.map(call, range(6)))
    assert codes == [200] * 5 + [201]
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(SetLog)) == 1


def test_first_log_starts_the_session_and_shows_in_the_views(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
    session = athlete.client.get(f"{BASE}/sessions/{sid}").json()
    assert_matches_schema(session, "Session")
    assert session["status"] == "in_progress"
    assert session["started_at"] is not None
    first_set = session["exercises"][0]["sets"][0]
    assert first_set["log"]["reps"] == 8
    assert first_set["log"]["weight_kg"] == 50
    assert session["exercises"][0]["sets"][1]["log"] is None
    day = athlete.client.get(f"{BASE}/athletes/me/days/{THU}").json()
    assert day["training_status"] == "in_progress"
    assert_matches_schema(day, "DayView")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"reps": 8}, "invalid_set"),  # strength needs weight too
        ({"weight_kg": 50}, "invalid_set"),
        ({"seconds": 30, "reps": 8, "weight_kg": 50}, "invalid_set"),  # wrong type
        ({"as_planned": True, "skipped": True}, "invalid_set"),
        ({"as_planned": True, "reps": 3}, "invalid_set"),
        ({"skipped": True, "weight_kg": 3}, "invalid_set"),
        ({}, "invalid_set"),
    ],
)
def test_set_validation_by_exercise_type(athlete: Api, body: dict[str, Any], code: str) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    problem(
        _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, **body), 422, code
    )


def test_timed_sets_use_seconds_and_distance(athlete: Api) -> None:
    sid, _, _, timed = _ids(_session(athlete))
    bad = _log(athlete, sid, exercise_id=timed, set_no=1, reps=3)
    problem(bad, 422, "invalid_set")
    ok = _log(athlete, sid, exercise_id=timed, set_no=1, seconds=300, distance_m=1200)
    assert ok.status_code == 201
    assert ok.json()["target_seconds"] == 600
    assert ok.json()["distance_m"] == 1200


def test_unknown_or_mismatched_references(athlete: Api) -> None:
    sid, ex, planned, timed = _ids(_session(athlete))
    problem(
        _log(athlete, sid, exercise_id=str(uuid.uuid4()), set_no=1, reps=1, weight_kg=1),
        404,
        "exercise_not_found",
    )
    problem(
        _log(athlete, sid, exercise_id=timed, planned_exercise_id=planned, set_no=1, seconds=5),
        422,
        "planned_exercise_mismatch",
    )
    assert _log(athlete, sid, exercise_id=ex, set_no=0, reps=1, weight_kg=1).status_code == 422
    assert (
        _log(athlete, sid, exercise_id=ex, set_no=1, reps=1, weight_kg=1, junk=1).status_code == 422
    )


def test_extra_sets_and_extra_exercises_are_kept_but_not_planned(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    with Session(athlete.app.state.engine) as db:
        extra_ex = db.scalars(
            select(Exercise).where(
                Exercise.owner_id.is_(None),
                Exercise.type == "strength",
                Exercise.id != uuid.UUID(ex),
            )
        ).first()
        assert extra_ex is not None
        extra_id = str(extra_ex.id)
    assert (
        _log(
            athlete,
            sid,
            exercise_id=ex,
            planned_exercise_id=planned,
            set_no=4,
            reps=10,
            weight_kg=50,
        ).status_code
        == 201
    )
    assert (
        _log(athlete, sid, exercise_id=extra_id, set_no=1, reps=10, weight_kg=20).status_code == 201
    )
    session = athlete.client.get(f"{BASE}/sessions/{sid}").json()
    assert_matches_schema(session, "Session")
    planned_ex, _timed, extra = session["exercises"]
    assert [s["is_extra"] for s in planned_ex["sets"]] == [False, False, False, True]
    assert extra["is_extra"] is True and extra["planned_exercise_id"] is None
    assert session["completion"] == 0.0 or session["completion"] is not None
    # Extras never count toward completion.
    assert session["completion"] == 0


def test_delete_set_removes_it_and_recomputes(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    log = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True
    ).json()
    assert athlete.client.get(f"{BASE}/sessions/{sid}").json()["completion"] > 0
    assert athlete.client.delete(f"{BASE}/sessions/{sid}/sets/{log['id']}").status_code == 204
    assert athlete.client.get(f"{BASE}/sessions/{sid}").json()["completion"] is None
    problem(
        athlete.client.delete(f"{BASE}/sessions/{sid}/sets/{log['id']}"), 404, "set_log_not_found"
    )


# ───────────── F10.2 completion ─────────────


def test_completion_is_sum_of_min_actual_target_over_planned_sets(athlete: Api) -> None:
    sid, ex, planned, timed = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, reps=8, weight_kg=50)
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=2, reps=4, weight_kg=50)
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=3, skipped=True)
    _log(athlete, sid, exercise_id=timed, set_no=1, seconds=1200)  # capped at the 600 s target
    result = _finish(athlete, sid)
    assert result.status_code == 200, result.text
    body = result.json()
    assert_matches_schema(body, "FinishSessionResult")
    # (8 + 4 + 0 + 600) / (24 + 600)
    assert body["session"]["completion"] == pytest.approx(612 / 624, abs=1e-4)
    strength = body["session"]["exercises"][0]
    assert strength["completion"] == pytest.approx(12 / 24, abs=1e-4)
    # Suggestions are covered by test_suggestions.py: one per performed exercise.
    assert [x["payload"]["exercise"]["type"] for x in body["suggestions"]] == ["strength", "timed"]


def test_unlogged_planned_sets_count_as_zero(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
    body = _finish(athlete, sid).json()
    assert body["session"]["completion"] == pytest.approx(8 / 624, abs=1e-4)


# ───────────── finish, kcal, F13.2 ─────────────


def test_finish_stores_kcal_from_the_engine_at_the_weight_on_the_session_date(athlete: Api) -> None:
    sid, ex, planned, timed = _ids(_session(athlete))
    for n in (1, 2, 3):
        _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=n, as_planned=True)
    _log(athlete, sid, exercise_id=timed, set_no=1, seconds=1800)
    _weight_now(athlete, 90.0, dt.date(2026, 10, 25))  # after the session date: must be ignored
    _weight_now(athlete, 70.0, dt.date(2026, 10, 10))  # the most recent one before the date
    _weight_now(athlete, 70.0, dt.date(2026, 10, 22))
    with Session(athlete.app.state.engine) as db:
        db.execute(
            update(BodyMetric)
            .where(BodyMetric.date == dt.date(2026, 10, 22))
            .values(weight_kg=72.5)
        )
        db.commit()
    body = _finish(athlete, sid).json()
    minutes = 3 * (90 + 45) / 60
    exact = _expected_kcal_exact(athlete, ex, 72.5, minutes) + _expected_kcal_exact(
        athlete, timed, 72.5, 30
    )
    assert body["session"]["kcal"] == math.floor(exact + 0.5)
    assert body["session"]["status"] == "done"
    assert body["session"]["finished_at"] is not None
    day = athlete.client.get(f"{BASE}/athletes/me/days/{THU}").json()
    assert day["energy"]["burned"]["training_kcal"] == body["session"]["kcal"]
    # A later weigh-in does not change the stored value.
    _weight_now(athlete, 99.0, dt.date(2026, 10, 23))
    assert athlete.client.get(f"{BASE}/sessions/{sid}").json()["kcal"] == body["session"]["kcal"]


def _expected_kcal_exact(api: Api, exercise_id: str, weight: float, minutes: float) -> float:
    with Session(api.app.state.engine) as session:
        met = session.get(Exercise, uuid.UUID(exercise_id)).met  # type: ignore[union-attr]
    return met * 3.5 * weight / 200 * minutes


def test_finish_with_explicit_time_and_its_validation(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
    problem(
        _finish(athlete, sid, body={"finished_at": "2026-10-23T09:00:00Z"}),
        422,
        "invalid_finished_at",
    )
    problem(
        _finish(athlete, sid, body={"finished_at": "2026-10-22T08:00:00Z"}),
        422,
        "invalid_finished_at",
    )
    ok = _finish(athlete, sid, body={"finished_at": "2026-10-22T09:00:00Z"})
    assert ok.status_code == 200
    assert ok.json()["session"]["finished_at"].startswith("2026-10-22T09:00:00")
    assert _finish(athlete, str(uuid.uuid4())).status_code == 403


def test_finishing_without_a_body_works_on_a_session_with_no_logs(athlete: Api) -> None:
    sid = _session(athlete)["id"]
    body = _finish(athlete, sid).json()
    assert body["session"]["status"] == "done"
    assert body["session"]["completion"] == 0
    assert body["session"]["kcal"] == 0


# ───────────── F10.3 edit window ─────────────


def test_finished_sessions_can_be_edited_until_the_end_of_the_next_day(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    for n in (1, 2, 3):
        _log(
            athlete,
            sid,
            exercise_id=ex,
            planned_exercise_id=planned,
            set_no=n,
            reps=8,
            weight_kg=50,
        )
    finished = _finish(athlete, sid).json()["session"]
    before = (finished["completion"], finished["kcal"])
    assert finished["editable_until"] == "2026-10-23T22:00:00Z"  # 24 Oct 00:00 in Madrid (UTC+2)

    # Next day, still inside the window: an edit recomputes completion and kcal.
    athlete.clock.set(dt.datetime(2026, 10, 23, 21, 59, tzinfo=dt.UTC))
    athlete.login()
    edited = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=3, reps=2, weight_kg=50
    )
    assert edited.status_code == 200
    after = athlete.client.get(f"{BASE}/sessions/{sid}").json()
    assert after["status"] == "done"
    assert after["completion"] < before[0]
    assert after["kcal"] == before[1]  # same performed sets, so same estimate
    extra = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=4, reps=8, weight_kg=50
    )
    assert extra.status_code == 201
    assert athlete.client.get(f"{BASE}/sessions/{sid}").json()["kcal"] >= before[1]
    skip = _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=4, skipped=True)
    assert skip.status_code == 200

    # Past the window: every mutation is rejected with 409 and nothing changes.
    athlete.clock.set(dt.datetime(2026, 10, 23, 22, 0, tzinfo=dt.UTC))
    athlete.login()
    snapshot = athlete.client.get(f"{BASE}/sessions/{sid}").json()
    problem(
        _log(
            athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, reps=1, weight_kg=1
        ),
        409,
        "edit_window_closed",
    )
    problem(_finish(athlete, sid), 409, "edit_window_closed")
    log_id = snapshot["exercises"][0]["sets"][0]["log"]["id"]
    problem(
        athlete.client.delete(f"{BASE}/sessions/{sid}/sets/{log_id}"), 409, "edit_window_closed"
    )
    assert athlete.client.get(f"{BASE}/sessions/{sid}").json() == snapshot


def test_refinishing_inside_the_window_does_not_count_a_second_workout(
    migrated_database_url: str,
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, spans, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    captured = Captured(app, telemetry, spans, reader)
    with TestClient(app) as client:
        api = Api(app=app, client=client, clock=app.state.clock)
        _seed_athlete(api)
        sid, ex, planned, _ = _ids(_session(api))
        _log(api, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
        _log(api, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
        _log(api, sid, exercise_id=ex, planned_exercise_id=planned, set_no=2, as_planned=True)
        assert _finish(api, sid).status_code == 200
        assert _finish(api, sid).status_code == 200
    assert [p.value for p in captured.metric_points("fitwise_sets_logged_total")] == [3]
    assert [p.value for p in captured.metric_points("fitwise_workouts_finished_total")] == [1]


# ───────────── F9.2 moved session ─────────────


def test_a_session_moved_to_thursday_logged_on_thursday_counts_for_thursday(api: Api) -> None:
    _seed_athlete(api, weekdays=("mon", "fri"))
    api.clock.set(dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC))  # Monday
    api.login()
    monday = _session(api, "2026-10-19")["id"]
    moved = api.client.post(f"{BASE}/sessions/{monday}/move", json={"date": THU})
    assert moved.status_code == 200, moved.text
    api.clock.set(NOW)  # Thursday
    api.login()
    sid, ex, planned, _ = _ids(_session(api, THU))
    assert sid == monday
    _log(api, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
    assert _finish(api, sid).status_code == 200
    thursday = api.client.get(f"{BASE}/athletes/me/days/{THU}").json()
    assert thursday["training_status"] == "done"
    assert thursday["training_completion"] is not None
    original = api.client.get(f"{BASE}/athletes/me/days/2026-10-19").json()
    assert original["session"] is None and original["training_status"] == "rest"
    week = api.client.get(
        f"{BASE}/athletes/me/calendar", params={"from": "2026-10-19", "to": "2026-10-25"}
    ).json()
    days = {d["date"]: d for d in week["days"]}
    assert days[THU]["training_status"] == "done" and days[THU]["moved"] is True
    assert days["2026-10-19"]["training_status"] == "rest"
    assert days[FRI]["training_status"] == "planned"  # the Friday template day is untouched


# ───────────── snapshots (rule 7) ─────────────


def test_set_logs_keep_the_targets_they_were_performed_against(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    log = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True
    ).json()
    assert (log["target_reps"], log["target_weight_kg"]) == (8, 50)
    with Session(athlete.app.state.engine) as db:
        db.execute(
            update(PlannedExercise)
            .where(PlannedExercise.id == uuid.UUID(planned))
            .values(reps_min=12, reps_max=12, target_weight_kg=80)
        )
        db.commit()
    again = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, reps=8, weight_kg=50
    ).json()
    assert (again["target_reps"], again["target_weight_kg"]) == (8, 50)  # re-logging keeps it
    shown = athlete.client.get(f"{BASE}/sessions/{sid}").json()["exercises"][0]["sets"]
    assert shown[0]["target_reps"] == 8 and shown[0]["target_weight_kg"] == 50
    assert shown[1]["target_reps"] == 12  # not yet logged: the current plan
    new_set = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=2, as_planned=True
    ).json()
    assert (new_set["target_reps"], new_set["target_weight_kg"]) == (12, 80)
    # Completion of the logged set still uses its snapshot (8 of 8).
    with Session(athlete.app.state.engine) as db:
        db.execute(
            update(PlannedExercise)
            .where(PlannedExercise.id == uuid.UUID(planned))
            .values(reps_min=100, reps_max=100)
        )
        db.commit()
    done = _finish(athlete, sid).json()["session"]["exercises"][0]
    assert done["completion"] == pytest.approx((8 + 12 + 0) / (8 + 12 + 100), abs=1e-4)


# ───────────── F10.4 extra activities ─────────────


def _timed(api: Api) -> str:
    with Session(api.app.state.engine) as db:
        return str(
            db.scalars(
                select(Exercise.id).where(Exercise.owner_id.is_(None), Exercise.type == "timed")
            ).first()
        )


def test_extra_activities_add_burned_kcal_on_a_rest_day_but_not_completion(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True)
    before = athlete.client.get(f"{BASE}/sessions/{sid}").json()["completion"]
    activity_ex = _timed(athlete)
    rest_day = "2026-10-21"  # Wednesday: no session planned
    response = athlete.client.post(
        f"{BASE}/athletes/me/activities",
        json={"date": rest_day, "exercise_id": activity_ex, "minutes": 60},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert_matches_schema(result, "ActivityResult")
    expected = _expected_kcal(athlete, activity_ex, 80.0, 60)
    assert result["activity"]["kcal"] == expected
    assert result["energy"]["burned"]["activities_kcal"] == expected
    assert result["energy"]["burned"]["total_kcal"] == expected
    day = athlete.client.get(f"{BASE}/athletes/me/days/{rest_day}").json()
    assert day["training_status"] == "rest"
    assert [a["id"] for a in day["activities"]] == [result["activity"]["id"]]
    assert day["energy"]["burned"]["activities_kcal"] == expected
    assert day["training_completion"] is None
    assert athlete.client.get(f"{BASE}/sessions/{sid}").json()["completion"] == before
    # On a training day it adds on top of the session, still without touching completion.
    athlete.client.post(
        f"{BASE}/athletes/me/activities",
        json={"date": THU, "exercise_id": activity_ex, "minutes": 30},
    )
    assert athlete.client.get(f"{BASE}/sessions/{sid}").json()["completion"] == before

    deleted = athlete.client.delete(f"{BASE}/athletes/me/activities/{result['activity']['id']}")
    assert deleted.status_code == 200
    assert_matches_schema(deleted.json(), "DayEnergyUpdate")
    assert deleted.json()["energy"]["burned"]["activities_kcal"] == 0
    problem(
        athlete.client.delete(f"{BASE}/athletes/me/activities/{result['activity']['id']}"),
        404,
        "activity_not_found",
    )


def test_activity_kcal_is_fixed_when_logged_and_validated(athlete: Api) -> None:
    activity_ex = _timed(athlete)
    _sid, ex, *_ = _ids(_session(athlete))
    body = {"date": THU, "exercise_id": activity_ex, "minutes": 45}
    first = athlete.client.post(f"{BASE}/athletes/me/activities", json=body).json()
    _weight_now(athlete, 100.0, dt.date(2026, 10, 23))
    day = athlete.client.get(f"{BASE}/athletes/me/days/{THU}").json()
    assert day["activities"][0]["kcal"] == first["activity"]["kcal"]
    problem(
        athlete.client.post(f"{BASE}/athletes/me/activities", json={**body, "exercise_id": ex}),
        422,
        "not_timed_exercise",
    )
    problem(
        athlete.client.post(
            f"{BASE}/athletes/me/activities", json={**body, "exercise_id": str(uuid.uuid4())}
        ),
        404,
        "exercise_not_found",
    )
    assert (
        athlete.client.post(
            f"{BASE}/athletes/me/activities", json={**body, "minutes": 0}
        ).status_code
        == 422
    )


# ───────────── authorization ─────────────


def test_only_the_owner_can_log_finish_or_delete(athlete: Api) -> None:
    sid, ex, planned, _ = _ids(_session(athlete))
    log = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=1, as_planned=True
    ).json()
    stranger = _stranger(athlete)
    coach = _stranger(athlete, "coach@x.test", role="coach")
    payload = {"exercise_id": ex, "set_no": 2, "reps": 1, "weight_kg": 1}
    for who in (stranger, coach):
        problem(who.post(f"{BASE}/sessions/{sid}/sets", json=payload), 403, "not_linked")
        problem(who.post(f"{BASE}/sessions/{sid}/finish"), 403, "not_linked")
        problem(who.delete(f"{BASE}/sessions/{sid}/sets/{log['id']}"), 403, "not_linked")
        problem(who.post(f"{BASE}/sessions/{uuid.uuid4()}/sets", json=payload), 403, "not_linked")
        assert who.post(f"{BASE}/sessions/not-a-uuid/finish").status_code == 400
    me = athlete.client.get(f"{BASE}/me").json()["id"]
    activity_ex = _timed(athlete)
    body = {"date": THU, "exercise_id": activity_ex, "minutes": 10}
    for who in (stranger, coach):
        problem(who.post(f"{BASE}/athletes/{me}/activities", json=body), 403, "not_linked")
    own = athlete.client.post(f"{BASE}/athletes/me/activities", json=body).json()["activity"]["id"]
    for who in (stranger, coach):
        problem(who.delete(f"{BASE}/athletes/{me}/activities/{own}"), 403, "not_linked")
    # A stranger's own endpoint cannot reach someone else's activity either.
    problem(stranger.delete(f"{BASE}/athletes/me/activities/{own}"), 404, "activity_not_found")
    assert (
        athlete.client.get(f"{BASE}/sessions/{sid}").json()["exercises"][0]["sets"][1]["log"]
        is None
    )
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(SetLog)) == 1
        assert db.scalar(select(func.count()).select_from(ExtraActivity)) == 1
        assert db.scalars(select(TrainingSession)).one().status == "in_progress"


def test_unauthenticated_requests_get_401(athlete: Api) -> None:
    anon = athlete.new_client()
    assert anon.post(f"{BASE}/sessions/{uuid.uuid4()}/sets", json={}).status_code == 401
    assert anon.post(f"{BASE}/sessions/{uuid.uuid4()}/finish").status_code == 401
    assert anon.post(f"{BASE}/athletes/me/activities", json={}).status_code == 401
