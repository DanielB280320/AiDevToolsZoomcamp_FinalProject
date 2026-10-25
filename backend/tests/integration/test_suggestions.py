"""#85 Suggestions against real Postgres: the finish hook (F11, F10.3), list, accept / reject
(F11.3), the session banner, the engine flag (F11.5), metrics and authorization."""

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import FeatureFlag, PlannedExercise, SetLog, Suggestion, User
from app.services import suggestions as svc
from tests.conftest import Captured, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem
from tests.integration.test_training_log import (
    BASE,
    FRI,
    THU,
    _finish,
    _ids,
    _log,
    _seed_athlete,
    _session,
    _stranger,
)

MONDAY = dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC)


def _perform(api: Api, day: str, reps: int = 8, weight: float = 50.0, sets: int = 3) -> str:
    """Log `sets` strength sets and finish the session of `day`; returns the session id."""
    sid, ex, planned, _ = _ids(_session(api, day))
    for n in range(1, sets + 1):
        response = _log(
            api, sid, exercise_id=ex, planned_exercise_id=planned, set_no=n, reps=reps,
            weight_kg=weight,
        )  # fmt: skip
        assert response.status_code in (200, 201), response.text
    assert _finish(api, sid).status_code == 200
    return sid


@pytest.fixture
def athlete(api: Api) -> Api:
    """An athlete whose Monday session is already done, so Thursday is not a calibration."""
    _seed_athlete(api)
    api.clock.set(MONDAY)
    api.login()
    _perform(api, "2026-10-19")
    api.clock.set(NOW)
    api.login()
    return api


def _list(api: Api, client: Any = None, athlete_id: str = "me", **params: Any) -> Any:
    return (client or api.client).get(f"{BASE}/athletes/{athlete_id}/suggestions", params=params)


def _pending_for(api: Api, session_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = _list(api).json()["items"]
    return [i for i in items if i["payload"]["source_session_id"] == session_id]


def _planned(api: Api, planned_id: str) -> PlannedExercise:
    with Session(api.app.state.engine) as session:
        row = session.get(PlannedExercise, uuid.UUID(planned_id))
        assert row is not None
        session.expunge(row)
        return row


# ───────────── finish hook ─────────────


def test_finish_creates_one_pending_suggestion_per_performed_exercise(athlete: Api) -> None:
    sid, ex, planned_id, _ = _ids(_session(athlete))
    for n in (1, 2, 3):
        _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned_id, set_no=n, reps=8,
             weight_kg=50)  # fmt: skip
    finished = _finish(athlete, sid)
    assert finished.status_code == 200
    body = finished.json()
    assert_matches_schema(body, "FinishSessionResult")
    (suggestion,) = body["suggestions"]  # the timed exercise was not performed: none for it
    assert suggestion["status"] == "pending" and suggestion["kind"] == "progression"
    assert suggestion["rule"] == "linear"
    assert suggestion["payload"]["planned_exercise_id"] == planned_id
    assert suggestion["payload"]["current"]["target_weight_kg"] == 50.0
    assert suggestion["payload"]["proposed"]["target_weight_kg"] > 50.0
    assert "reps" in suggestion["reason"] and suggestion["inputs"]["rule"] == "linear"
    assert suggestion["decided_by"] is None and suggestion["decided_at"] is None
    with Session(athlete.app.state.engine) as session:
        stored = session.scalars(select(Suggestion).where(Suggestion.session_id == uuid.UUID(sid)))
        (row,) = stored
        assert (row.rule, row.reason, row.status) == (
            suggestion["rule"], suggestion["reason"], "pending")  # fmt: skip
        assert row.inputs["engine_version"] == "v1"


def test_the_first_session_of_an_exercise_calibrates(api: Api) -> None:
    _seed_athlete(api)
    sid, ex, planned_id, _ = _ids(_session(api))
    _log(api, sid, exercise_id=ex, planned_exercise_id=planned_id, set_no=1, reps=8, weight_kg=45)
    (suggestion,) = _finish(api, sid).json()["suggestions"]
    assert suggestion["rule"] == "calibration"
    assert suggestion["payload"]["proposed"]["target_weight_kg"] == 45.0


def test_manual_and_skipped_exercises_create_no_suggestion(athlete: Api) -> None:
    sid, ex, planned_id, _ = _ids(_session(athlete))
    with Session(athlete.app.state.engine) as session:
        session.execute(
            update(PlannedExercise)
            .where(PlannedExercise.id == uuid.UUID(planned_id))
            .values(rule="manual")
        )
        session.commit()
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned_id, set_no=1, reps=8,
         weight_kg=50)  # fmt: skip
    assert _finish(athlete, sid).json()["suggestions"] == []
    assert _pending_for(athlete, sid) == []


def test_a_fully_skipped_exercise_creates_no_suggestion(athlete: Api) -> None:
    sid, ex, planned_id, _ = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned_id, set_no=1, skipped=True)
    assert _finish(athlete, sid).json()["suggestions"] == []


def test_a_failed_session_holds_with_the_engine_reason(athlete: Api) -> None:
    sid = _perform(athlete, THU, reps=5)
    (suggestion,) = _pending_for(athlete, sid)
    assert suggestion["payload"]["proposed"]["target_weight_kg"] == 50.0
    assert suggestion["inputs"]["consecutive_failures_after"] == 1


# ───────────── F10.3 recompute ─────────────


def test_editing_a_finished_session_replaces_its_pending_suggestions(athlete: Api) -> None:
    sid = _perform(athlete, THU, reps=8)
    (first,) = _pending_for(athlete, sid)
    assert first["payload"]["proposed"]["target_weight_kg"] > 50.0
    _, ex, planned_id, _ = _ids(_session(athlete))
    # Edit set 3 down to 5 reps inside the window: the suggestion is recomputed (a hold).
    edit = _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned_id, set_no=3, reps=5,
                weight_kg=50)  # fmt: skip
    assert edit.status_code == 200
    (second,) = _pending_for(athlete, sid)
    assert second["id"] != first["id"]
    assert second["payload"]["proposed"]["target_weight_kg"] == 50.0
    # Finishing again also leaves exactly one.
    assert len(_finish(athlete, sid).json()["suggestions"]) == 1
    assert len(_pending_for(athlete, sid)) == 1


def test_deleting_a_set_of_a_finished_session_recomputes(athlete: Api) -> None:
    sid = _perform(athlete, THU, reps=8)
    (first,) = _pending_for(athlete, sid)
    with Session(athlete.app.state.engine) as session:
        log_id = session.scalars(
            select(SetLog.id).where(SetLog.session_id == uuid.UUID(sid), SetLog.set_no == 3)
        ).one()
    assert athlete.client.delete(f"{BASE}/sessions/{sid}/sets/{log_id}").status_code == 204
    (second,) = _pending_for(athlete, sid)
    assert second["id"] != first["id"]
    assert second["payload"]["proposed"]["target_weight_kg"] == 50.0


def test_recompute_leaves_decided_suggestions_alone(athlete: Api) -> None:
    sid = _perform(athlete, THU, reps=8)
    (first,) = _pending_for(athlete, sid)
    assert athlete.client.post(f"{BASE}/suggestions/{first['id']}/reject").status_code == 200
    assert _finish(athlete, sid).status_code == 200
    assert _pending_for(athlete, sid) == []  # not re-created for the decided exercise
    rejected = _list(athlete, status="rejected").json()["items"]
    assert [i["id"] for i in rejected if i["payload"]["source_session_id"] == sid] == [first["id"]]


def test_logging_in_an_unfinished_session_creates_nothing(athlete: Api) -> None:
    sid, ex, planned_id, _ = _ids(_session(athlete))
    _log(athlete, sid, exercise_id=ex, planned_exercise_id=planned_id, set_no=1, reps=8,
         weight_kg=50)  # fmt: skip
    assert _pending_for(athlete, sid) == []


# ───────────── list ─────────────


def test_list_defaults_to_pending_newest_first_and_filters(athlete: Api) -> None:
    athlete.clock.set(NOW)
    thu = _perform(athlete, THU)
    athlete.clock.set(NOW + dt.timedelta(days=1))
    athlete.login()
    fri = _perform(athlete, FRI)
    response = _list(athlete)
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "SuggestionList")
    assert body["weigh_in_hint"] is None
    sources = [i["payload"]["source_session_id"] for i in body["items"]]
    assert sources[:2] == [fri, thu]  # newest first; Monday's is older still
    assert len(sources) == 3
    assert all(i["status"] == "pending" for i in body["items"])
    assert _list(athlete, kind="calories").json()["items"] == []
    assert len(_list(athlete, kind="progression").json()["items"]) == 3
    assert _list(athlete, status="accepted").json()["items"] == []
    assert _list(athlete, status="nope").status_code == 400
    assert _list(athlete, kind="nope").status_code == 400


def test_list_is_forbidden_for_other_athletes_and_unlinked_coaches(athlete: Api) -> None:
    with Session(athlete.app.state.engine) as session:
        ana = session.scalars(select(User.id).where(User.email == "ana@x.test")).one()
    other = _stranger(athlete)
    coach = _stranger(athlete, "coach@x.test", role="coach")
    for client in (other, coach):
        problem(_list(athlete, client, athlete_id=str(ana)), 403, "not_linked")
    problem(_list(athlete, coach, athlete_id="me"), 403, "not_linked")  # coaches have no list
    assert _list(athlete, other).json()["items"] == []  # "me" is the caller's own, empty, list
    assert _list(athlete, athlete_id=str(ana)).status_code == 200
    anonymous = athlete.new_client()
    problem(_list(athlete, anonymous), 401, "not_authenticated")


# ───────────── accept ─────────────


def test_accept_updates_targets_and_leaves_history_untouched(athlete: Api) -> None:
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    planned_id = suggestion["payload"]["planned_exercise_id"]
    proposed = suggestion["payload"]["proposed"]
    with Session(athlete.app.state.engine) as session:
        snapshots = [
            (log.id, log.target_weight_kg, log.target_reps)
            for log in session.scalars(select(SetLog).where(SetLog.session_id == uuid.UUID(sid)))
        ]
    athlete.clock.set(NOW + dt.timedelta(hours=1))
    response = athlete.client.post(f"{BASE}/suggestions/{suggestion['id']}/accept")
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_schema(body, "Suggestion")
    assert body["status"] == "accepted"
    assert body["decided_by"]["role"] == "athlete"
    assert body["decided_at"].startswith("2026-10-22T10:00:00")
    assert body["payload"]["applied"] == proposed
    planned = _planned(athlete, planned_id)
    assert planned.target_weight_kg == proposed["target_weight_kg"]
    assert planned.reps_min == proposed["reps_min"]
    with Session(athlete.app.state.engine) as session:
        after = [
            (log.id, log.target_weight_kg, log.target_reps)
            for log in session.scalars(select(SetLog).where(SetLog.session_id == uuid.UUID(sid)))
        ]
    assert sorted(after) == sorted(snapshots)  # set log target snapshots unchanged
    assert [i["id"] for i in _list(athlete).json()["items"] if i["id"] == suggestion["id"]] == []


def test_accept_with_overrides_applies_the_edited_values(athlete: Api) -> None:
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    response = athlete.client.post(
        f"{BASE}/suggestions/{suggestion['id']}/accept",
        json={"overrides": {"target_weight_kg": 51.0, "reps_min": 6, "reps_max": 6}},
    )
    assert response.status_code == 200, response.text
    applied = response.json()["payload"]["applied"]
    assert applied["target_weight_kg"] == 51.0 and applied["reps_min"] == applied["reps_max"] == 6
    planned = _planned(athlete, suggestion["payload"]["planned_exercise_id"])
    assert (planned.target_weight_kg, planned.reps_min, planned.reps_max) == (51.0, 6, 6)


@pytest.mark.parametrize(
    "overrides",
    [
        {"kcal": 2000},  # a calorie override on a progression suggestion
        {"target_seconds": 60},  # seconds on a strength exercise
        {"reps_min": 6, "reps_max": 7},  # linear exercises have one rep target
    ],
)
def test_overrides_of_the_wrong_kind_are_422_and_change_nothing(
    athlete: Api, overrides: dict[str, int]
) -> None:
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    response = athlete.client.post(
        f"{BASE}/suggestions/{suggestion['id']}/accept", json={"overrides": overrides}
    )
    problem(response, 422, "invalid_overrides")
    assert len(_pending_for(athlete, sid)) == 1
    assert _planned(athlete, suggestion["payload"]["planned_exercise_id"]).target_weight_kg == 50.0
    # Malformed overrides are rejected by the schema itself.
    bad = athlete.client.post(
        f"{BASE}/suggestions/{suggestion['id']}/accept", json={"overrides": {}}
    )
    assert bad.status_code == 422


def test_deciding_twice_is_409_and_does_not_change_the_first_decision(athlete: Api) -> None:
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    path = f"{BASE}/suggestions/{suggestion['id']}"
    assert athlete.client.post(f"{path}/accept").status_code == 200
    problem(athlete.client.post(f"{path}/accept"), 409, "suggestion_already_decided")
    problem(athlete.client.post(f"{path}/reject"), 409, "suggestion_already_decided")
    accepted = _list(athlete, status="accepted").json()["items"]
    assert [i["id"] for i in accepted if i["id"] == suggestion["id"]]


def test_deciding_another_athletes_or_an_unknown_suggestion_is_403(athlete: Api) -> None:
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    other = _stranger(athlete)
    coach = _stranger(athlete, "coach@x.test", role="coach")
    for client in (other, coach):
        for action in ("accept", "reject"):
            path = f"{BASE}/suggestions/{suggestion['id']}/{action}"
            problem(client.post(path), 403, "not_linked")
    unknown = f"{BASE}/suggestions/{uuid.uuid4()}/accept"
    problem(athlete.client.post(unknown), 403, "not_linked")
    problem(athlete.new_client().post(f"{BASE}/suggestions/{suggestion['id']}/accept"), 401,
            "not_authenticated")  # fmt: skip
    assert len(_pending_for(athlete, sid)) == 1


# ───────────── reject, banner ─────────────


def test_reject_changes_only_the_suggestion_and_the_next_finish_suggests_again(
    athlete: Api,
) -> None:
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    planned_id = suggestion["payload"]["planned_exercise_id"]
    before = _planned(athlete, planned_id)
    response = athlete.client.post(f"{BASE}/suggestions/{suggestion['id']}/reject")
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_schema(body, "Suggestion")
    assert body["status"] == "rejected" and body["decided_by"] is not None
    assert body["payload"]["applied"] is None
    after = _planned(athlete, planned_id)
    assert (after.target_weight_kg, after.reps_min, after.reps_max) == (
        before.target_weight_kg, before.reps_min, before.reps_max)  # fmt: skip
    # The same weekday, a week later: a fresh pending suggestion for the same exercise.
    athlete.clock.set(NOW + dt.timedelta(days=7))
    athlete.login()
    next_sid = _perform(athlete, "2026-10-29")
    (fresh,) = _pending_for(athlete, next_sid)
    assert fresh["id"] != suggestion["id"] and fresh["status"] == "pending"
    assert fresh["payload"]["planned_exercise_id"] == planned_id


def test_a_session_with_a_pending_suggestion_uses_current_targets_and_flags_it(
    athlete: Api,
) -> None:
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    done = _session(athlete, THU)
    strength = done["exercises"][0]
    assert strength["pending_suggestion_id"] == suggestion["id"]
    assert done["exercises"][1]["pending_suggestion_id"] is None
    # A session of the same weekday next week is not materialised from the suggestion.
    next_week = _session(athlete, "2026-10-29")["exercises"][0]
    assert next_week["pending_suggestion_id"] == suggestion["id"]
    assert next_week["sets"][0]["target_weight_kg"] == 50.0
    # After acceptance the banner is gone and the new target applies.
    athlete.client.post(f"{BASE}/suggestions/{suggestion['id']}/accept")
    later = _session(athlete, "2026-10-29")["exercises"][0]
    assert later["pending_suggestion_id"] is None
    assert later["sets"][0]["target_weight_kg"] == suggestion["payload"]["proposed"][
        "target_weight_kg"]  # fmt: skip


# ───────────── F11.5 engine flag ─────────────


@pytest.mark.parametrize("stored", ["v1", "v2", "v99", ""])
def test_stored_engine_values_run_v1(athlete: Api, stored: str) -> None:
    with Session(athlete.app.state.engine) as session:
        session.add(
            FeatureFlag(key="progression_engine", value=stored, updated_by="owner", updated_at=NOW)
        )
        session.commit()
    athlete.app.state.flags.invalidate()
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    assert suggestion["inputs"]["engine_version"] == "v1"
    assert suggestion["payload"]["proposed"]["target_weight_kg"] > 50.0


def test_engine_for_selects_by_version_and_falls_back_to_v1() -> None:
    assert svc.engine_for("v1") is svc.ENGINES["v1"]
    assert svc.engine_for("v2") is svc.ENGINES["v1"]
    assert svc.engine_for("garbage") is svc.ENGINES["v1"]


def test_the_flag_selects_the_engine_version(athlete: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With a second engine registered, `progression_engine = v2` is the one that runs."""
    from app.engines import progression

    def v2(p: progression.ProgressionInput) -> progression.Suggestion:
        base = progression.suggest(p)
        return progression.Suggestion(
            base.rule, "hold", p.target_weight_kg, base.reps, base.seconds, "v2 says hold",
            base.consecutive_failures, base.inputs,
        )  # fmt: skip

    monkeypatch.setitem(svc.ENGINES, "v2", v2)
    with Session(athlete.app.state.engine) as session:
        session.add(
            FeatureFlag(key="progression_engine", value="v2", updated_by="owner", updated_at=NOW)
        )
        session.commit()
    athlete.app.state.flags.invalidate()
    sid = _perform(athlete, THU)
    (suggestion,) = _pending_for(athlete, sid)
    assert suggestion["reason"] == "v2 says hold"
    assert suggestion["inputs"]["engine_version"] == "v2"


# ───────────── metrics ─────────────


def test_generated_and_decided_metrics_increment_once_per_event(
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
        sid = _perform(api, THU)  # first session of the exercise: calibration
        (suggestion,) = _pending_for(api, sid)
        assert client.post(f"{BASE}/suggestions/{suggestion['id']}/accept").status_code == 200
        assert client.post(f"{BASE}/suggestions/{suggestion['id']}/accept").status_code == 409

    def points(name: str) -> dict[tuple[tuple[str, Any], ...], Any]:
        return {
            tuple(sorted(p.attributes.items())): p.value
            for p in captured.metric_points(name)
            if p.value
        }

    assert points("fitwise_suggestions_generated_total") == {
        (("kind", "progression"), ("rule", "calibration")): 1
    }
    assert points("fitwise_suggestions_decided_total") == {
        (("decision", "accepted"), ("kind", "progression")): 1
    }
