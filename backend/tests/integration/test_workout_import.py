"""#57 CSV import of past workouts (F10.5, D89) against real Postgres: format and limits,
all-or-nothing, plan-less sessions, idempotency, no progression, deletes outside the edit window,
authorization (owner / linked coach / stranger) and privacy of logs and telemetry."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Exercise, SetLog, Suggestion, TrainingSession
from tests.conftest import Captured, JsonLogs, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem, signup_body
from tests.integration.test_training_log import _seed_athlete

BASE = "/api/v1"
URL = f"{BASE}/athletes/me/imports/workouts"
HEADER = "date,exercise,set,reps,weight_kg,duration_seconds,distance_m"


@pytest.fixture
def athlete(api: Api) -> Api:
    _seed_athlete(api)
    return api


def _names(api: Api) -> dict[str, str]:
    with Session(api.app.state.engine) as db:
        out: dict[str, str] = {}
        for kind in ("strength", "bodyweight", "timed"):
            out[kind] = db.scalars(
                select(Exercise.name).where(Exercise.owner_id.is_(None), Exercise.type == kind)
            ).first()  # type: ignore[assignment]
        return out


def _csv(*lines: str) -> bytes:
    return ("\n".join([HEADER, *lines]) + "\n").encode()


def _upload(client: TestClient, data: bytes, url: str = URL) -> Any:
    return client.post(url, files={"file": ("workouts.csv", data, "text/csv")})


def _count(api: Api, model: Any) -> int:
    with Session(api.app.state.engine) as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _two_days(api: Api) -> bytes:
    n = _names(api)
    return _csv(
        f"2026-08-03,{n['strength']},1,8,60,,",
        f"2026-08-03,{n['strength'].upper()},2,6,62.5,,",
        f"2026-08-04,{n['timed']},1,,,1800,5000",
    )


def _coach_linked(api: Api) -> TestClient:
    coach = api.new_client()
    r = coach.post(f"{BASE}/auth/signup", json=signup_body(email="coach@x.test", role="coach"))
    assert r.status_code == 201, r.text
    link = api.client.post(f"{BASE}/coach-links", json={"coach_id": r.json()["id"]})
    assert link.status_code == 201, link.text
    assert coach.post(f"{BASE}/coach-links/{link.json()['id']}/approve").status_code == 200
    return coach


# ───────────── happy path ─────────────


def test_import_creates_one_finished_plan_less_session_per_date(athlete: Api) -> None:
    r = _upload(athlete.client, _two_days(athlete))
    assert r.status_code == 200, r.text
    assert_matches_schema(r.json(), "WorkoutImportResult")
    assert r.json() == {"imported": 3, "skipped": 0}
    with Session(athlete.app.state.engine) as db:
        rows = list(db.scalars(select(TrainingSession).where(TrainingSession.imported.is_(True))))
        assert sorted(str(s.date) for s in rows) == ["2026-08-03", "2026-08-04"]
        assert all(s.status == "done" and s.plan_id is None for s in rows)
        assert all(s.training_day_id is None and s.completion is None for s in rows)
        assert all(s.kcal is not None for s in rows)  # F13.2 with the 80 kg weigh-in
        sets = list(db.scalars(select(SetLog)))
        assert len(sets) == 3
        assert all(
            s.target_reps is None
            and s.target_weight_kg is None
            and s.target_seconds is None
            and s.planned_exercise_id is None
            for s in sets
        )
    day = athlete.client.get(f"{BASE}/athletes/me/days/2026-08-03").json()
    assert_matches_schema(day, "DayView")
    session = day["session"]
    assert session["imported"] is True and session["plan_id"] is None
    assert session["training_day_name"] is None and session["status"] == "done"
    assert [s["log"]["reps"] for s in session["exercises"][0]["sets"]] == [8, 6]


def test_imported_sets_feed_history_charts_and_prs_but_not_progression(athlete: Api) -> None:
    assert _upload(athlete.client, _two_days(athlete)).status_code == 200
    with Session(athlete.app.state.engine) as db:
        strength = db.scalars(
            select(Exercise.id).where(Exercise.owner_id.is_(None), Exercise.type == "strength")
        ).first()
        assert db.scalar(select(func.count()).select_from(Suggestion)) == 0
    chart = athlete.client.get(f"{BASE}/athletes/me/charts/exercise/{strength}?weeks=52")
    assert chart.status_code == 200, chart.text
    points = chart.json()["points"]
    assert len(points) == 1 and points[0]["date"] == "2026-08-03"
    assert points[0]["target_weight_kg"] is None  # no target line
    assert points[0]["top_set_weight_kg"] == 62.5 and points[0]["is_pr"] is True
    cal = athlete.client.get(f"{BASE}/athletes/me/calendar?from=2026-08-03&to=2026-08-04").json()
    assert [d["training_status"] for d in cal["days"]] == ["done", "done"]
    energy = athlete.client.get(f"{BASE}/athletes/me/days/2026-08-04").json()["energy"]
    assert energy["burned"]["training_kcal"] > 0
    sid = athlete.client.get(f"{BASE}/athletes/me/days/2026-08-03").json()["session"]["id"]
    chart_session = athlete.client.get(f"{BASE}/athletes/me/charts/session/{sid}")
    assert chart_session.status_code == 200, chart_session.text
    assert_matches_schema(chart_session.json(), "SessionChart")


def test_matching_is_case_insensitive_and_exact(athlete: Api) -> None:
    n = _names(athlete)
    ok = _upload(athlete.client, _csv(f"2026-08-03,  {n['strength'].lower()} ,1,8,60,,"))
    assert ok.json() == {"imported": 1, "skipped": 0}
    partial = _upload(athlete.client, _csv(f"2026-08-04,{n['strength'][:-1]},1,8,60,,"))
    assert partial.status_code == 422


def test_reuploading_the_same_file_imports_nothing_and_skips_every_row(athlete: Api) -> None:
    data = _two_days(athlete)
    assert _upload(athlete.client, data).json() == {"imported": 3, "skipped": 0}
    again = _upload(athlete.client, data)
    assert again.status_code == 200
    assert again.json() == {"imported": 0, "skipped": 3}
    assert _count(athlete, SetLog) == 3
    assert _count(athlete, TrainingSession) == 2


def test_a_later_file_adds_new_sets_to_an_imported_day(athlete: Api) -> None:
    n = _names(athlete)
    _upload(athlete.client, _csv(f"2026-08-03,{n['strength']},1,8,60,,"))
    r = _upload(
        athlete.client,
        _csv(f"2026-08-03,{n['strength']},1,8,60,,", f"2026-08-03,{n['strength']},2,8,60,,"),
    )
    assert r.json() == {"imported": 1, "skipped": 1}
    with Session(athlete.app.state.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(TrainingSession).where(TrainingSession.imported)
            )
            == 1
        )


# ───────────── rejection: all or nothing ─────────────


def test_an_invalid_row_rejects_the_whole_file_and_echoes_no_content(athlete: Api) -> None:
    n = _names(athlete)
    data = _csv(
        f"2026-08-03,{n['strength']},1,8,60,,",
        "2026-08-03,Secret Lift Name,1,8,61.25,,",
        f"2026-08-04,{n['strength']},1,8,60,,",
    )
    r = _upload(athlete.client, data)
    body = problem(r, 422, "invalid_import")
    assert [(e["field"], e["message"]) for e in body["errors"]] == [("rows.3", "unknown exercise")]
    assert "Secret Lift Name" not in r.text and "61.25" not in r.text
    assert _count(athlete, SetLog) == 0
    assert _count(athlete, TrainingSession) == 0


def test_at_most_20_row_errors_are_listed(athlete: Api) -> None:
    body = problem(
        _upload(athlete.client, _csv(*["2026-08-03,Nope,1,8,60,,"] * 30)), 422, "invalid_import"
    )
    assert len(body["errors"]) == 20
    assert body["errors"][0]["field"] == "rows.2"


def test_a_day_with_a_real_session_is_rejected(athlete: Api) -> None:
    n = _names(athlete)
    assert athlete.client.get(f"{BASE}/athletes/me/days/2026-10-22").status_code == 200
    r = _upload(athlete.client, _csv(f"2026-10-22,{n['strength']},1,8,60,,"))
    body = problem(r, 422, "invalid_import")
    assert body["errors"][0]["field"] == "rows.2"
    assert _count(athlete, SetLog) == 0


def test_future_dates_are_rejected_in_the_athletes_time_zone(athlete: Api) -> None:
    n = _names(athlete)
    # NOW is 2026-10-22 09:00 UTC = 11:00 in Madrid: the 22nd is today, the 23rd is the future.
    ok = _upload(athlete.client, _csv(f"2026-10-21,{n['strength']},1,8,60,,"))
    assert ok.status_code == 200
    bad = _upload(athlete.client, _csv(f"2026-10-23,{n['strength']},1,8,60,,"))
    problem(bad, 422, "invalid_import")


def test_limits_and_encoding(athlete: Api) -> None:
    n = _names(athlete)
    too_big = b"x" * (2 * 1024 * 1024 + 1)
    problem(_upload(athlete.client, too_big), 413, "file_too_large")
    rows = [f"2026-08-03,{n['strength']},{k % 30 + 1},8,60,," for k in range(5001)]
    problem(_upload(athlete.client, _csv(*rows)), 422, "too_many_rows")
    problem(_upload(athlete.client, b"\xff\xfe\x00bad"), 422, "invalid_import")
    problem(_upload(athlete.client, b"date,exercise\n"), 422, "invalid_import")
    assert _count(athlete, SetLog) == 0
    missing = athlete.client.post(URL)
    assert missing.status_code in (400, 422)


def test_a_bom_and_crlf_line_endings_are_accepted(athlete: Api) -> None:
    n = _names(athlete)
    data = "﻿" + HEADER + "\r\n" + f"2026-08-03,{n['strength']},1,8,60,,\r\n"
    assert _upload(athlete.client, data.encode()).json() == {"imported": 1, "skipped": 0}


# ───────────── deleting imported sets ─────────────


def test_imported_sets_can_be_deleted_outside_the_edit_window(athlete: Api) -> None:
    _upload(athlete.client, _two_days(athlete))
    session = athlete.client.get(f"{BASE}/athletes/me/days/2026-08-03").json()["session"]
    log = session["exercises"][0]["sets"][0]["log"]
    r = athlete.client.delete(f"{BASE}/sessions/{session['id']}/sets/{log['id']}")
    assert r.status_code == 204, r.text
    assert _count(athlete, SetLog) == 2
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Suggestion)) == 0
    # Editing (not deleting) a closed imported day stays inside the window rule.
    other = session["exercises"][0]["sets"][1]["log"]
    edit = athlete.client.post(
        f"{BASE}/sessions/{session['id']}/sets",
        json={"exercise_id": other["exercise_id"], "set_no": 2, "reps": 5, "weight_kg": 10},
    )
    problem(edit, 409, "edit_window_closed")


# ───────────── authorization ─────────────


def test_a_linked_coach_is_forbidden_and_a_stranger_is_denied(athlete: Api) -> None:
    coach = _coach_linked(athlete)
    stranger = athlete.new_client()
    assert (
        stranger.post(
            f"{BASE}/auth/signup", json=signup_body(email="bo@x.test", role="athlete")
        ).status_code
        == 201
    )
    data = _two_days(athlete)
    aid = athlete.client.get(f"{BASE}/me").json()["id"]
    by_coach = _upload(coach, data, f"{BASE}/athletes/{aid}/imports/workouts")
    problem(by_coach, 403, "wrong_role")
    by_stranger = _upload(stranger, data, f"{BASE}/athletes/{aid}/imports/workouts")
    problem(by_stranger, 403, "not_linked")
    by_coach_me = _upload(coach, data)
    assert by_coach_me.status_code == 403
    assert _upload(athlete.new_client(), data).status_code == 401
    assert _count(athlete, SetLog) == 0
    assert (
        _upload(athlete.client, data, f"{BASE}/athletes/{aid}/imports/workouts").status_code == 200
    )
    # The linked coach can read the imported history, but not delete from it.
    session = coach.get(f"{BASE}/athletes/{aid}/days/2026-08-03").json()["session"]
    assert session["imported"] is True
    log_id = session["exercises"][0]["sets"][0]["log"]["id"]
    assert coach.delete(f"{BASE}/sessions/{session['id']}/sets/{log_id}").status_code == 403


def test_another_athletes_custom_exercise_is_not_matched(athlete: Api) -> None:
    other = athlete.new_client()
    assert other.post(f"{BASE}/auth/signup", json=signup_body(email="o@x.test")).status_code == 201
    made = other.post(
        f"{BASE}/exercises",
        json={
            "name": "Zebra Curl",
            "muscle_group": "biceps",
            "equipment": "dumbbell",
            "type": "strength",
            "met": 5,
            "region": "upper",
        },
    )
    assert made.status_code == 201, made.text
    problem(_upload(athlete.client, _csv("2026-08-03,Zebra Curl,1,8,10,,")), 422, "invalid_import")


# ───────────── privacy ─────────────


def test_logs_metrics_and_traces_carry_counts_only(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    captured = Captured(app, telemetry, span_exporter, metric_reader)
    api = Api(app=app, client=TestClient(app), clock=app.state.clock)
    with api.client:
        _seed_athlete(api)
        n = _names(api)
        good = _csv(f"2026-08-03,{n['strength']},1,8,61.25,,")
        bad = _csv("2026-08-03,Hidden Squat Variant,1,8,77.75,,")
        assert _upload(api.client, good).status_code == 200
        assert _upload(api.client, good).status_code == 200
        assert _upload(api.client, bad).status_code == 422
    blob = json_logs.text
    for span in captured.spans():
        blob += str(span.to_json())
    data = captured.metric_reader.get_metrics_data()
    assert data is not None
    blob += str(data.to_json())
    for secret in (n["strength"], "Hidden Squat Variant", "61.25", "77.75", "workouts.csv"):
        assert secret not in blob
    lines = json_logs.with_message("workouts imported")
    assert [line["count"] for line in lines] == [1, 0]
