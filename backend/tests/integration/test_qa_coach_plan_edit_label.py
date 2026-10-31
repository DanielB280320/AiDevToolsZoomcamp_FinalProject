"""QA (#48, F8): a coach edit makes the plan `custom` and labels the day with the coach; the athlete
sees the label; a later hand edit by the athlete replaces it (the UI shows it only for coaches)."""

from typing import Any

from sqlalchemy.orm import Session

from app.seed import run_seed
from tests.integration.test_coach_dashboard import World, w  # noqa: F401  (fixture)
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_plan_editor import _training_body

API = "/api/v1"


def _get_plan(client: Any, athlete: str) -> dict[str, Any]:
    r = client.get(f"{API}/athletes/{athlete}/plan")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_coach_edit_is_custom_and_labelled_then_athlete_edit_replaces_label(w: World) -> None:  # noqa: F811
    with Session(w.api.app.state.engine) as db:
        run_seed(db)
    ana = w.athlete("Ana")
    assert ana.client.post(ONBOARD, json=onboarding()).status_code == 201

    plan = _get_plan(w.cleo.client, str(ana.id))
    assert plan["source"] == "generated"
    body = _training_body(plan)
    body["training_days"][0]["exercises"][0]["sets"] = 5
    r = w.cleo.client.put(f"{API}/athletes/{ana.id}/plan/training", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "custom"

    seen_by_athlete = _get_plan(ana.client, "me")
    day = seen_by_athlete["training_days"][0]
    assert day["edited_by"] == {"id": str(w.cleo.id), "display_name": "Cleo Coach", "role": "coach"}
    assert [d["edited_by"] for d in seen_by_athlete["training_days"][1:]] == [None] * (
        len(seen_by_athlete["training_days"]) - 1
    )

    body = _training_body(seen_by_athlete)
    body["training_days"][0]["exercises"][0]["sets"] = 4
    r = ana.client.put(f"{API}/athletes/me/plan/training", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["training_days"][0]["edited_by"]["role"] == "athlete"
