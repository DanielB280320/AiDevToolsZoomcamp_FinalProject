"""#43 Chart data API (F15) against real Postgres: session detail, exercise over time (target
snapshots, PR markers), adherence, weekly summary, body; empty states; authorization."""

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import PlannedExercise
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem, signup_body
from tests.integration.chart_data import (
    Seeded,
    add_activity,
    add_meals,
    add_session,
    add_weight,
    seed_plan,
)
from tests.integration.test_training_log import _finish, _ids, _log, _seed_athlete, _session

BASE = "/api/v1/athletes/me/charts"
TODAY = dt.date(2026, 10, 22)  # Thursday
D = dt.timedelta


def get(api: Api, path: str, **params: Any) -> Any:
    return api.client.get(f"{BASE}/{path}", params=params)


def ok(api: Api, path: str, schema: str, **params: Any) -> dict[str, Any]:
    response = get(api, path, **params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_matches_schema(body, schema)
    return body


@pytest.fixture
def seeded(api: Api) -> tuple[Api, Seeded]:
    return api, seed_plan(api)


# ───────────── session detail ─────────────


def test_session_chart_target_vs_actual_per_set_and_snapshots(api: Api) -> None:
    _seed_athlete(api)
    sid, ex, planned, timed = _ids(_session(api))
    kw = {"exercise_id": ex, "planned_exercise_id": planned}
    _log(api, sid, set_no=1, reps=8, weight_kg=50, **kw)
    _log(api, sid, set_no=2, reps=5, weight_kg=50, **kw)
    _log(api, sid, set_no=3, skipped=True, **kw)
    _log(api, sid, set_no=4, reps=6, weight_kg=40, **kw)  # extra set
    _log(api, sid, set_no=1, exercise_id=timed, seconds=600)
    _finish(api, sid)
    with Session(api.app.state.engine) as db:  # the plan changes after the session was logged
        db.execute(
            update(PlannedExercise)
            .where(PlannedExercise.id == uuid.UUID(planned))
            .values(reps_min=12, reps_max=12, target_weight_kg=90)
        )
        db.commit()
    body = ok(api, f"session/{sid}", "SessionChart")
    assert body["session_id"] == sid and body["date"] == "2026-10-22"
    assert body["status"] == "done" and body["kcal"] is not None
    strength, cardio = body["exercises"]
    assert [(s["set_no"], s["status"]) for s in strength["sets"]] == [
        (1, "met"), (2, "partial"), (3, "skipped"), (4, "extra"),
    ]  # fmt: skip
    first = strength["sets"][0]
    assert (first["target_reps"], first["target_weight_kg"]) == (8, 50)  # snapshot, not 12/90
    assert (first["reps"], first["weight_kg"]) == (8, 50)
    assert strength["sets"][1]["completion"] == pytest.approx(5 / 8, abs=1e-4)
    assert strength["sets"][3]["completion"] is None  # extra sets have nothing to complete
    assert strength["is_extra"] is False
    assert [s["status"] for s in cardio["sets"]] == ["met"]
    assert cardio["sets"][0]["target_seconds"] == 600


def test_session_chart_unlogged_sets_are_missed(api: Api) -> None:
    _seed_athlete(api)
    sid, *_ = _ids(_session(api))
    body = ok(api, f"session/{sid}", "SessionChart")
    assert body["status"] == "planned"
    assert [s["status"] for s in body["exercises"][0]["sets"]] == ["missed"] * 3
    assert body["exercises"][0]["completion"] is None


def test_session_chart_of_someone_elses_or_unknown_session_is_403(api: Api) -> None:
    _seed_athlete(api)
    sid, *_ = _ids(_session(api))
    other = api.new_client()
    other.post("/api/v1/auth/signup", json=signup_body(email="bo@x.test"))
    for client, target in ((other, sid), (api.client, str(uuid.uuid4()))):
        r = client.get(f"{BASE}/session/{target}")
        assert problem(r, 403, "not_linked")


# ───────────── exercise over time ─────────────


def _history(api: Api, seed: Seeded) -> None:
    """Thursdays/Mondays with rising weights; the target snapshot rises 50 -> 52.5 -> 55."""
    with Session(api.app.state.engine) as db:
        add_session(db, seed, dt.date(2026, 9, 3), sets=[(8, 50, 8, 50), (8, 50, 8, 50)])
        add_session(db, seed, dt.date(2026, 10, 1), sets=[(8, 52.5, 8, 52.5), (8, 52.5, 8, 52.5)])
        add_session(db, seed, dt.date(2026, 10, 8), sets=[(8, 50, 8, 52.5), (6, 50, 8, 52.5)])
        add_session(
            db,
            seed,
            dt.date(2026, 10, 15),
            sets=[(8, 55, 8, 55), (8, 55, 8, 55), (8, 57, 8, 55)],
            skipped_sets=(),
        )
        # not finished, and a skipped set: neither shapes the series
        add_session(db, seed, dt.date(2026, 10, 12), sets=[(8, 99, 8, 55)], status="in_progress")
        db.commit()


def test_exercise_chart_uses_target_snapshots_and_marks_prs(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    _history(api, seed)
    with Session(api.app.state.engine) as db:  # current plan target changes: history must not
        db.execute(update(PlannedExercise).values(target_weight_kg=200))
        db.commit()
    body = ok(api, f"exercise/{seed.strength_id}", "ExerciseChart", weeks=12)
    assert body["weeks"] == 12 and body["exercise"]["id"] == str(seed.strength_id)
    points = body["points"]
    assert [p["date"] for p in points] == ["2026-09-03", "2026-10-01", "2026-10-08", "2026-10-15"]
    assert [p["target_weight_kg"] for p in points] == [50, 52.5, 52.5, 55]
    assert [p["top_set_weight_kg"] for p in points] == [50, 52.5, 50, 57]
    assert [p["is_pr"] for p in points] == [True, True, False, True]
    assert points[0]["volume_kg"] == 800 and points[2]["volume_kg"] == 8 * 50 + 6 * 50
    assert points[3]["volume_kg"] == 8 * 55 * 2 + 8 * 57


def test_exercise_chart_ranges_and_pr_account_for_earlier_history(
    seeded: tuple[Api, Seeded],
) -> None:
    api, seed = seeded
    _history(api, seed)
    with Session(api.app.state.engine) as db:
        add_session(db, seed, dt.date(2026, 6, 1), sets=[(8, 70, 8, 70)])  # 20 weeks ago
        db.commit()
    four = ok(api, f"exercise/{seed.strength_id}", "ExerciseChart", weeks=4)["points"]
    assert [p["date"] for p in four] == ["2026-10-01", "2026-10-08", "2026-10-15"]
    # 70 kg in June stays the record: nothing in the range beats it
    assert not any(p["is_pr"] for p in four)
    twenty_six = ok(api, f"exercise/{seed.strength_id}", "ExerciseChart", weeks=26)["points"]
    assert twenty_six[0]["date"] == "2026-06-01" and twenty_six[0]["is_pr"] is True
    default = ok(api, f"exercise/{seed.strength_id}", "ExerciseChart")
    assert default["weeks"] == 12 and len(default["points"]) == 4


def test_exercise_chart_empty_and_errors(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    assert ok(api, f"exercise/{seed.strength_id}", "ExerciseChart")["points"] == []
    assert problem(get(api, f"exercise/{seed.strength_id}", weeks=5), 400, "bad_request")
    assert problem(get(api, f"exercise/{uuid.uuid4()}"), 404, "exercise_not_found")


def test_exercise_chart_timed_exercise(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    with Session(api.app.state.engine) as db:
        add_session(db, seed, dt.date(2026, 10, 1), timed_seconds=500)
        add_session(db, seed, dt.date(2026, 10, 8), timed_seconds=620)
        db.commit()
    points = ok(api, f"exercise/{seed.timed_id}", "ExerciseChart")["points"]
    assert [(p["top_set_seconds"], p["target_seconds"], p["is_pr"]) for p in points] == [
        (500, 600, True), (620, 600, True),
    ]  # fmt: skip
    assert points[0]["volume_kg"] == 0


# ───────────── adherence ─────────────


def test_adherence_days_weeks_and_nutrition(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    mon, thu = dt.date(2026, 10, 19), dt.date(2026, 10, 22)
    with Session(api.app.state.engine) as db:
        add_session(db, seed, mon, sets=[(8, 50, 8, 50)] * 3, completion=0.8)
        add_meals(db, seed, mon, ("eaten", "adjusted", "skipped"))  # 2 of 3
        add_meals(db, seed, dt.date(2026, 10, 20), ("eaten", "eaten", "eaten"))
        add_session(db, seed, thu, status="in_progress", completion=0.25)
        db.commit()
    body = ok(api, "adherence", "AdherenceChart", **{"from": "2026-10-19", "to": "2026-10-25"})
    assert (body["from"], body["to"]) == ("2026-10-19", "2026-10-25")
    days = {d["date"]: d for d in body["days"]}
    assert len(days) == 7
    assert (days["2026-10-19"]["training_status"], days["2026-10-19"]["training_completion"]) == (
        "done", 0.8,
    )  # fmt: skip
    assert days["2026-10-19"]["nutrition_completion"] == pytest.approx(2 / 3, abs=1e-4)
    assert days["2026-10-20"]["training_status"] == "rest"
    assert days["2026-10-20"]["training_completion"] is None
    assert days["2026-10-20"]["nutrition_completion"] == 1.0
    assert days["2026-10-21"]["nutrition_completion"] == 0.0  # planned meals, none eaten
    assert days["2026-10-22"]["training_status"] == "in_progress"
    assert days["2026-10-22"]["training_completion"] == 0.25
    friday = days["2026-10-23"]  # future: nothing to rate yet
    assert (friday["training_status"], friday["training_completion"]) == ("planned", None)
    assert friday["nutrition_completion"] is None
    (week,) = body["weeks"]
    assert week["week_start"] == "2026-10-19"
    assert (week["sessions_planned"], week["sessions_done"]) == (3, 1)
    assert week["training_completion"] == pytest.approx((0.8 + 0.25) / 2, abs=1e-4)
    assert week["nutrition_completion"] == pytest.approx((2 / 3 + 1 + 0 + 0) / 4, abs=1e-3)


def test_adherence_missed_past_sessions_count_as_zero_and_weeks_split_on_monday(
    seeded: tuple[Api, Seeded],
) -> None:
    api, _ = seeded
    body = ok(api, "adherence", "AdherenceChart", **{"from": "2026-10-11", "to": "2026-10-18"})
    days = {d["date"]: d for d in body["days"]}
    assert days["2026-10-12"]["training_status"] == "missed"  # Monday, nothing logged
    assert days["2026-10-12"]["training_completion"] == 0.0
    assert [w["week_start"] for w in body["weeks"]] == ["2026-10-05", "2026-10-12"]
    assert body["weeks"][0]["sessions_planned"] == 0  # only Sunday 11th falls in that week


def test_adherence_range_rules_and_empty_state(api: Api) -> None:
    assert api.signup().status_code == 201
    empty = ok(api, "adherence", "AdherenceChart", **{"from": "2026-10-20", "to": "2026-10-22"})
    assert {d["training_status"] for d in empty["days"]} == {"rest"}
    assert all(d["nutrition_completion"] is None for d in empty["days"])
    assert problem(
        get(api, "adherence", **{"from": "2026-10-23", "to": "2026-10-22"}), 400, "invalid_range"
    )
    too_big = get(api, "adherence", **{"from": "2025-10-18", "to": "2026-10-22"})  # 370 days
    assert too_big.status_code == 200
    too_big = get(api, "adherence", **{"from": "2025-10-17", "to": "2026-10-22"})  # 371 days
    assert too_big.status_code == 200
    r = get(api, "adherence", **{"from": "2025-10-16", "to": "2026-10-22"})  # 372 days
    assert problem(r, 400, "range_too_large")
    assert get(api, "adherence").status_code == 422 or get(api, "adherence").status_code == 400


# ───────────── weekly summary ─────────────


def test_weekly_summary_numbers(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    mon, thu = dt.date(2026, 10, 19), dt.date(2026, 10, 22)
    with Session(api.app.state.engine) as db:
        add_session(db, seed, mon, sets=[(8, 50, 8, 50)] * 3, completion=0.8)
        add_meals(db, seed, mon, ("eaten", "eaten", "eaten"))
        add_activity(db, seed, mon)
        add_weight(db, seed, dt.date(2026, 10, 17), 80.0)
        add_weight(db, seed, mon, 79.0)
        add_weight(db, seed, thu, 78.0)
        db.commit()
    body = ok(api, "weekly-summary", "WeeklySummary")
    assert (body["week_start"], body["week_end"]) == ("2026-10-19", "2026-10-25")
    assert body["estimated"] is True
    assert (body["sessions_planned"], body["sessions_done"], body["sessions_missed"]) == (3, 1, 0)
    assert body["avg_completion"] == 0.8
    assert body["target_daily_balance_kcal"] == -300
    assert body["avg_daily_balance_kcal"] is not None  # only Monday has food logged
    assert body["weight_avg_start_kg"] == 79.5  # mean(80, 79): window 13..19 Oct
    assert body["weight_avg_end_kg"] == 79.0  # mean(80, 79, 78): window 16..22 Oct
    assert body["weight_change_kg"] == -0.5
    spark = body["sparklines"]
    assert spark["weight_avg_kg"][0]["date"] == "2026-10-19"
    assert spark["weight_avg_kg"][3]["value"] == 79.0
    assert spark["weight_avg_kg"][4]["value"] is None  # future days have no value
    balance = [p["value"] for p in spark["daily_balance_kcal"]]
    assert balance[0] is not None and balance[1:] == [None] * 6
    assert spark["training_completion"][0]["value"] == 0.8
    # Only Monday has food logged, so the average equals Monday's balance in the day view.
    day = api.client.get("/api/v1/athletes/me/days/2026-10-19").json()
    assert body["avg_daily_balance_kcal"] == day["energy"]["balance_kcal"]


def test_weekly_summary_other_weeks_validation_and_empty(seeded: tuple[Api, Seeded]) -> None:
    api, _ = seeded
    past = ok(api, "weekly-summary", "WeeklySummary", week_start="2026-10-12")
    assert (past["sessions_planned"], past["sessions_missed"]) == (3, 3)
    assert past["avg_completion"] == 0.0  # missed sessions count as 0
    assert past["avg_daily_balance_kcal"] is None and past["weight_change_kg"] is None
    future = ok(api, "weekly-summary", "WeeklySummary", week_start="2026-11-02")
    assert future["sessions_planned"] == 3 and future["avg_completion"] is None
    assert future["avg_daily_balance_kcal"] is None and future["weight_avg_end_kg"] is None
    assert problem(get(api, "weekly-summary", week_start="2026-10-21"), 400, "bad_request")


# ───────────── body ─────────────


def test_body_chart_average_uses_only_existing_weigh_ins(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    with Session(api.app.state.engine) as db:
        add_weight(db, seed, dt.date(2026, 9, 20), 82.0)  # outside 4 weeks, inside the window
        add_weight(db, seed, dt.date(2026, 9, 27), 81.0)
        add_weight(db, seed, dt.date(2026, 9, 29), 80.0, fat=20.5)
        add_weight(db, seed, dt.date(2026, 10, 2), None, fat=20.0)  # body fat only
        add_weight(db, seed, dt.date(2026, 10, 20), 79.0)
        db.commit()
    body = ok(api, "body", "BodyChart", weeks=4)
    assert body["weeks"] == 4 and body["estimated"] is True
    by_date = {p["date"]: p for p in body["points"]}
    assert "2026-09-20" not in by_date  # before the range start (2026-09-25)
    assert by_date["2026-09-27"]["weight_avg_7d_kg"] == 81.0  # the 20th is out of its window
    assert by_date["2026-09-29"]["weight_avg_7d_kg"] == 80.5
    assert by_date["2026-09-29"]["body_fat_pct"] == 20.5
    assert by_date["2026-10-02"]["weight_kg"] is None
    assert by_date["2026-10-02"]["weight_avg_7d_kg"] == 80.5  # 27, 29 (2 Oct is body fat only)
    assert by_date["2026-10-20"]["weight_avg_7d_kg"] == 79.0
    assert [p["date"] for p in body["points"]] == sorted(by_date)
    wide = ok(api, "body", "BodyChart", weeks=12)
    assert "2026-09-20" in {p["date"] for p in wide["points"]}


def test_body_chart_empty_default_and_invalid_weeks(api: Api) -> None:
    assert api.signup().status_code == 201
    body = ok(api, "body", "BodyChart")
    assert body["weeks"] == 12 and body["points"] == []
    assert problem(get(api, "body", weeks=13), 400, "bad_request")


# ───────────── totals to date ─────────────


def test_totals_count_finished_sessions_and_records_over_the_whole_history(
    seeded: tuple[Api, Seeded],
) -> None:
    api, seed = seeded
    _history(api, seed)  # strength tops 50, 52.5, 50, 57: three records; one unfinished session
    with Session(api.app.state.engine) as db:
        add_session(db, seed, dt.date(2025, 6, 2), sets=[(8, 40, 8, 40)])  # over a year ago
        add_session(db, seed, dt.date(2026, 10, 19), timed_seconds=500)  # first timed: a record
        add_session(db, seed, dt.date(2026, 10, 22), timed_seconds=450)  # today, no record
        add_session(db, seed, dt.date(2026, 10, 23), sets=[(8, 99, 8, 55)])  # tomorrow: ignored
        db.commit()
    body = ok(api, "totals", "ProgressTotals")
    # 40 (2025), 50, 52.5 and 57 kg are records, 50 kg on 8 Oct is not; plus the first timed one.
    assert body == {"sessions_done": 7, "personal_records": 5, "first_session_date": "2025-06-02"}


def test_totals_ignore_skipped_sets_and_are_zero_without_history(
    seeded: tuple[Api, Seeded],
) -> None:
    api, seed = seeded
    empty = {"sessions_done": 0, "personal_records": 0, "first_session_date": None}
    assert ok(api, "totals", "ProgressTotals") == empty
    with Session(api.app.state.engine) as db:
        add_session(db, seed, dt.date(2026, 10, 1), sets=[(8, 50, 8, 50)])
        add_session(db, seed, dt.date(2026, 10, 8), sets=[(8, 60, 8, 60)], skipped_sets=(1,))
        db.commit()
    body = ok(api, "totals", "ProgressTotals")
    assert body == {"sessions_done": 2, "personal_records": 1, "first_session_date": "2026-10-01"}


# ───────────── period summary (D109) ─────────────

FRI, MON, THU = dt.date(2026, 10, 16), dt.date(2026, 10, 19), dt.date(2026, 10, 22)
PERIOD = {"from": "2026-10-16", "to": "2026-10-22"}  # Fri..Thu (today); previous 9..15 Oct


def _two_periods(api: Api, seed: Seeded) -> None:
    with Session(api.app.state.engine) as db:
        # previous period: Fri 9 + Mon 12 done (records), Thu 15 missed
        add_session(db, seed, dt.date(2026, 10, 9), sets=[(8, 40, 8, 40)] * 2)
        add_session(db, seed, dt.date(2026, 10, 12), sets=[(8, 45, 8, 45)] * 2)
        add_weight(db, seed, dt.date(2026, 10, 15), 79.0)
        # current period: Fri 16 done (record), Mon 19 missed, Thu 22 (today) in progress
        add_session(db, seed, FRI, sets=[(8, 50, 8, 50)] * 3)
        add_session(db, seed, THU, status="in_progress", completion=0.5)
        add_meals(db, seed, FRI, ("eaten", "eaten", "eaten"))
        add_activity(db, seed, FRI)
        add_weight(db, seed, THU, 78.0)
        db.commit()


def test_period_summary_current_previous_deltas_streak_and_series(
    seeded: tuple[Api, Seeded],
) -> None:
    api, seed = seeded
    _two_periods(api, seed)
    body = ok(api, "period-summary", "PeriodSummary", **PERIOD)
    assert (body["from"], body["to"], body["days"]) == ("2026-10-16", "2026-10-22", 7)
    assert (body["previous_from"], body["previous_to"]) == ("2026-10-09", "2026-10-15")
    assert body["bucket"] == "day" and body["estimated"] is True
    cur, prev, deltas = body["current"], body["previous"], body["deltas"]
    assert (cur["sessions_planned"], cur["sessions_done"], cur["sessions_missed"]) == (3, 1, 1)
    assert (prev["sessions_planned"], prev["sessions_done"], prev["sessions_missed"]) == (3, 2, 1)
    assert cur["active_days"] == 1 and prev["active_days"] == 2
    assert cur["avg_training_completion"] == pytest.approx((0.9 + 0 + 0.5) / 3, abs=1e-4)
    assert prev["avg_training_completion"] == pytest.approx((0.9 + 0.9 + 0) / 3, abs=1e-4)
    assert cur["avg_nutrition_completion"] == pytest.approx(1 / 7, abs=1e-4)  # only Friday eaten
    assert prev["avg_nutrition_completion"] == 0.0
    assert (cur["volume_kg"], prev["volume_kg"]) == (3 * 8 * 50, 2 * 8 * 40 + 2 * 8 * 45)
    assert (cur["personal_records"], prev["personal_records"]) == (1, 2)
    assert body["longest_streak_days"] == 1  # Fri done, Mon missed, Thu in progress
    # Energy: only Friday has food logged (D77); it matches the day view.
    day = api.client.get(f"/api/v1/athletes/me/days/{FRI.isoformat()}").json()["energy"]
    assert cur["avg_daily_eaten_kcal"] == day["eaten"]["kcal"] > 0
    assert cur["avg_daily_balance_kcal"] == day["balance_kcal"]
    assert cur["avg_daily_burned_exercise_kcal"] == 300 + 200  # session kcal + extra activity
    assert cur["target_daily_balance_kcal"] == -300
    assert prev["avg_daily_eaten_kcal"] is None and prev["avg_daily_balance_kcal"] is None
    # Weight: 7-day averages on the first and on the last day (Thu 22).
    assert (cur["weight_avg_start_kg"], cur["weight_avg_end_kg"]) == (79.0, 78.0)
    assert cur["weight_change_kg"] == -1.0
    assert cur["weight_change_per_week_kg"] == pytest.approx(-1.0 / 6 * 7, abs=0.01)
    assert prev["weight_avg_start_kg"] is None and prev["weight_change_kg"] is None
    assert prev["weight_avg_end_kg"] == 79.0
    # Deltas are computed on the server; null when a side is null.
    assert deltas["sessions_done"] == -1 and deltas["volume_kg"] == -160
    assert deltas["personal_records"] == -1
    assert deltas["avg_training_completion"] == pytest.approx(0.4667 - 0.6, abs=1e-3)
    assert deltas["avg_daily_balance_kcal"] is None and deltas["weight_change_kg"] is None
    # Series: one point per day, nothing after today.
    series = body["series"]
    assert [p["start"] for p in series] == [(FRI + D(days=n)).isoformat() for n in range(7)]
    assert series[0]["sessions_done"] == 1 and series[0]["volume_kg"] == 1200
    assert series[0]["balance_kcal"] == day["balance_kcal"] and series[1]["balance_kcal"] is None
    assert series[0]["training_completion"] == 0.9 and series[1]["training_completion"] is None
    assert series[3]["training_completion"] == 0.0  # Mon 19: missed counts as 0
    assert series[3]["sessions_planned"] == 1 and series[6]["sessions_planned"] == 1
    assert series[0]["weight_avg_kg"] == 79.0 and series[6]["weight_avg_kg"] == 78.0


def test_period_summary_weeks_bucket_and_days_after_today_count_nothing(
    seeded: tuple[Api, Seeded],
) -> None:
    api, seed = seeded
    _two_periods(api, seed)
    # 60 days ending 7 days after today: weeks, the last Monday-based bucket is today's week.
    body = ok(api, "period-summary", "PeriodSummary", **{"from": "2026-09-03", "to": "2026-10-29"})
    assert body["bucket"] == "week" and body["days"] == 57
    starts = [p["start"] for p in body["series"]]
    assert starts[0] == "2026-08-31" and starts[-1] == "2026-10-19"  # Mondays; 26 Oct not shown
    assert all(dt.date.fromisoformat(s).weekday() == 0 for s in starts)
    last = body["series"][-1]  # Mon 19 .. Thu 22 only: planned Mon, Thu; Fri 23 is the future
    assert last["sessions_planned"] == 2 and last["sessions_done"] == 0
    assert sum(p["volume_kg"] for p in body["series"]) == body["current"]["volume_kg"] == 2560
    future = ok(
        api, "period-summary", "PeriodSummary", **{"from": "2026-10-25", "to": "2026-10-31"}
    )
    assert future["series"] == [] and future["longest_streak_days"] == 0
    assert future["current"]["sessions_planned"] == 0
    assert future["current"]["avg_training_completion"] is None
    assert future["current"]["weight_avg_end_kg"] is None


def test_period_summary_empty_state(api: Api) -> None:
    assert api.signup().status_code == 201
    body = ok(api, "period-summary", "PeriodSummary", **PERIOD)
    assert body["current"]["sessions_planned"] == 0 and body["current"]["volume_kg"] == 0
    assert body["current"]["avg_training_completion"] is None
    assert body["deltas"]["volume_kg"] == 0 and body["deltas"]["avg_daily_balance_kcal"] is None
    assert len(body["series"]) == 7 and body["longest_streak_days"] == 0


def test_period_summary_range_rules(api: Api) -> None:
    assert api.signup().status_code == 201
    assert problem(
        get(api, "period-summary", **{"from": "2026-10-23", "to": "2026-10-22"}),
        400,
        "invalid_range",
    )
    assert (
        get(api, "period-summary", **{"from": "2025-10-17", "to": "2026-10-22"}).status_code == 200
    )
    r = get(api, "period-summary", **{"from": "2025-10-16", "to": "2026-10-22"})  # 372 days
    assert problem(r, 400, "range_too_large")
    assert get(api, "period-summary", **{"from": "2026-10-16"}).status_code == 400
    assert get(api, "period-summary", to="2026-10-16").status_code == 400
    assert get(api, "period-summary").status_code == 400


def test_period_summary_year_uses_a_fixed_number_of_queries(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    with Session(api.app.state.engine) as db:
        for n in range(0, 200, 3):
            day = THU - D(days=n)
            if day.weekday() in (0, 3, 4):
                add_session(db, seed, day, sets=[(8, 50, 8, 50)])
            add_weight(db, seed, day, 80.0)
        db.commit()
    counts: list[int] = []
    from sqlalchemy import event

    engine = api.app.state.engine
    for days in (7, 371):
        seen: list[str] = []

        def count(*args: Any, _seen: list[str] = seen) -> None:
            _seen.append(args[2])

        event.listen(engine, "before_cursor_execute", count)
        try:
            start = (THU - D(days=days - 1)).isoformat()
            assert (
                get(api, "period-summary", **{"from": start, "to": "2026-10-22"}).status_code == 200
            )
        finally:
            event.remove(engine, "before_cursor_execute", count)
        counts.append(len(seen))
    assert counts[1] <= counts[0] + 2, counts  # no query per day


def test_exercise_and_body_charts_accept_from_and_to(seeded: tuple[Api, Seeded]) -> None:
    api, seed = seeded
    _history(api, seed)
    with Session(api.app.state.engine) as db:
        add_weight(db, seed, dt.date(2026, 10, 6), 81.0)
        add_weight(db, seed, dt.date(2026, 10, 9), 80.0)
        add_weight(db, seed, dt.date(2026, 10, 20), 79.0)
        db.commit()
    path = f"exercise/{seed.strength_id}"
    one = ok(api, path, "ExerciseChart", **{"from": "2026-10-01", "to": "2026-10-08"}, weeks=4)
    assert [p["date"] for p in one["points"]] == ["2026-10-01", "2026-10-08"]  # weeks ignored
    assert [p["is_pr"] for p in one["points"]] == [True, False]  # still vs. earlier history
    assert one["weeks"] == 2  # 8 days, rounded up
    # `weeks` keeps working when there is no range, and is not validated when there is one
    assert len(ok(api, path, "ExerciseChart", weeks=4)["points"]) == 3
    assert get(api, path, **{"from": "2026-10-01", "to": "2026-10-08"}, weeks=5).status_code == 200
    body = ok(api, "body", "BodyChart", **{"from": "2026-10-07", "to": "2026-10-19"})
    assert [p["date"] for p in body["points"]] == ["2026-10-09"]  # 6 Oct is out, 20 Oct is out
    assert body["points"][0]["weight_avg_7d_kg"] == 80.5  # the 6th still feeds the window
    for route in (path, "body"):
        assert problem(get(api, route, **{"from": "2026-10-01"}), 400, "bad_request")
        assert problem(get(api, route, to="2026-10-01"), 400, "bad_request")
        assert problem(
            get(api, route, **{"from": "2026-10-09", "to": "2026-10-01"}), 400, "invalid_range"
        )
        r = get(api, route, **{"from": "2025-10-16", "to": "2026-10-22"})
        assert problem(r, 400, "range_too_large")


# ───────────── authorization ─────────────

PATHS = [
    "session/{sid}",
    "exercise/{ex}",
    "exercise/{ex}?from=2026-10-01&to=2026-10-22",
    "adherence?from=2026-10-19&to=2026-10-25",
    "weekly-summary",
    "period-summary?from=2026-10-16&to=2026-10-22",
    "body",
    "body?from=2026-10-01&to=2026-10-22",
    "totals",
]


@pytest.mark.parametrize("path", PATHS)
def test_owner_ok_stranger_coach_and_anonymous_refused(api: Api, path: str) -> None:
    seed = seed_plan(api)
    with Session(api.app.state.engine) as db:
        row = add_session(db, seed, dt.date(2026, 10, 19), sets=[(8, 50, 8, 50)])
        db.commit()
        sid = str(row.id)
    path = path.format(sid=sid, ex=seed.strength_id)
    owner = api.client.get(f"/api/v1/athletes/me/charts/{path}")
    assert owner.status_code == 200, owner.text
    by_id = api.client.get(f"/api/v1/athletes/{seed.uid}/charts/{path}")
    assert by_id.status_code == 200

    def clients() -> dict[str, TestClient]:
        stranger = api.new_client()
        assert (
            stranger.post("/api/v1/auth/signup", json=signup_body(email="bo@x.test")).status_code
            == 201
        )
        coach = api.new_client()
        r = coach.post("/api/v1/auth/signup", json=signup_body(email="cy@x.test", role="coach"))
        assert r.status_code == 201
        return {"stranger": stranger, "coach": coach}

    for name, client in clients().items():
        r = client.get(f"/api/v1/athletes/{seed.uid}/charts/{path}")
        assert problem(r, 403, "not_linked"), name
    # Coach access for a *linked* coach arrives with #47 (coach linking does not exist yet); this
    # test then gains the linked case.
    anonymous = api.new_client().get(f"/api/v1/athletes/{seed.uid}/charts/{path}")
    assert anonymous.status_code == 401
    assert api.client.get(f"/api/v1/athletes/not-a-uuid/charts/{path}").status_code == 400
