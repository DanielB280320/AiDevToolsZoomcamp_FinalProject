"""QA (#85): accepting a suggestion must leave finished sessions unchanged (issue AC, CLAUDE.md
rule 7, spec F8.1 "past sessions and logs never change")."""

from typing import Any

from tests.integration.auth_helpers import Api
from tests.integration.test_suggestions import _pending_for, athlete  # noqa: F401 - fixture
from tests.integration.test_training_log import BASE, THU, _finish, _ids, _log, _session


def _partial_thursday(api: Api) -> tuple[str, str, str]:
    """Log 2 of the 3 planned sets (8 reps at 50 kg) and finish; returns (sid, ex, planned)."""
    sid, ex, planned, _ = _ids(_session(api, THU))
    for n in (1, 2):
        response = _log(
            api, sid, exercise_id=ex, planned_exercise_id=planned, set_no=n, reps=8, weight_kg=50
        )
        assert response.status_code in (200, 201), response.text
    assert _finish(api, sid).status_code == 200
    return sid, ex, planned


def _strength(session: dict[str, Any]) -> dict[str, Any]:
    strength: dict[str, Any] = session["exercises"][0]
    return strength


def test_accepting_does_not_change_what_a_finished_session_shows(athlete: Api) -> None:  # noqa: F811
    sid, _, _ = _partial_thursday(athlete)
    (suggestion,) = _pending_for(athlete, sid)
    before = _strength(_session(athlete, THU))
    assert before["sets"][2]["log"] is None  # set 3 was never logged

    response = athlete.client.post(
        f"{BASE}/suggestions/{suggestion['id']}/accept",
        json={"overrides": {"target_weight_kg": 55.0, "reps_min": 10, "reps_max": 10}},
    )
    assert response.status_code == 200, response.text

    after = _strength(_session(athlete, THU))
    # The finished Thursday session is in the past relative to the decision: unchanged.
    assert after["sets"][2]["target_weight_kg"] == before["sets"][2]["target_weight_kg"]
    assert after["sets"][2]["target_reps"] == before["sets"][2]["target_reps"]
    assert (after["reps_min"], after["reps_max"]) == (before["reps_min"], before["reps_max"])
    assert after["completion"] == before["completion"]


def test_logging_into_a_finished_session_after_accept_snapshots_its_own_targets(
    athlete: Api,  # noqa: F811
) -> None:
    sid, ex, planned = _partial_thursday(athlete)
    (suggestion,) = _pending_for(athlete, sid)
    response = athlete.client.post(
        f"{BASE}/suggestions/{suggestion['id']}/accept",
        json={"overrides": {"target_weight_kg": 55.0, "reps_min": 10, "reps_max": 10}},
    )
    assert response.status_code == 200, response.text
    # Still inside Thursday's edit window: the athlete adds the set they forgot to log.
    logged = _log(
        athlete, sid, exercise_id=ex, planned_exercise_id=planned, set_no=3, reps=8, weight_kg=50
    )
    assert logged.status_code in (200, 201), logged.text
    body = logged.json()
    # That set was planned at 8 x 50 kg on Thursday, not at the values accepted afterwards.
    assert (body["target_reps"], body["target_weight_kg"]) == (8, 50.0)
