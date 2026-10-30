"""QA probes for #39 (F8 plan editor, D75): calendar start after an edit, past sessions,
gram-override copies, pending suggestions on a meal edit, and regenerate vs. meal logs."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Meal, MealItem, Suggestion
from app.seed import run_seed
from tests.integration.auth_helpers import Api
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_plan_editor import (
    LAST_THU,
    ME,
    THU,
    _day,
    _log,
    _meals_body,
    _plan,
    _put,
    _seed_athlete,
    _targets,
    _training_body,
    _user_id,
)

LAST_MON = "2026-10-19"  # past training day this week, before NOW (Thu 2026-10-22)


@pytest.fixture
def athlete(api: Api) -> Api:
    _seed_athlete(api)
    return api


def _own_meals(api: Api) -> int:
    with Session(api.app.state.engine) as session:
        return int(
            session.scalar(
                select(func.count()).select_from(Meal).where(Meal.owner_id == _user_id(api))
            )
            or 0
        )


def test_qa_calendar_start_stays_at_first_plan_and_past_sessions_keep_their_version(
    athlete: Api,
) -> None:
    missed = _day(athlete.client, LAST_MON)["session"]  # opened before the edit (past, no logs)
    assert missed is not None and missed["plan_version"] == 1
    snapshot = _targets(missed)
    body = _training_body(_plan(athlete.client))
    for d in body["training_days"]:
        d["exercises"][0].update(sets=5, reps_min=12, reps_max=12)
    assert _put(athlete.client, "training", body).status_code == 200

    after = _day(athlete.client, LAST_MON)["session"]
    assert after["id"] == missed["id"] and after["plan_version"] == 1
    assert _targets(after) == snapshot
    # A past day never opened before the edit still has a session: the template did not start
    # again at the edit's created_at (D75 (4)).
    assert _day(athlete.client, LAST_THU)["session"] is not None


def test_qa_grams_equal_to_the_base_reuse_it_and_a_repeat_save_reuses_the_copy(
    athlete: Api,
) -> None:
    plan = _plan(athlete.client)
    body = _meals_body(plan)
    target = body["meal_days"][0]["meals"][0]
    with Session(athlete.app.state.engine) as session:
        items: list[dict[str, Any]] = [
            {"food_id": str(i.food_id), "grams": float(i.grams)}
            for i in session.scalars(
                select(MealItem)
                .where(MealItem.meal_id == uuid.UUID(target["meal_id"]))
                .order_by(MealItem.position)
            )
        ]
    target["items"] = items
    response = _put(athlete.client, "meals", body)
    assert response.status_code == 200, response.text
    assert response.json()["meal_days"][0]["meals"][0]["meal"]["id"] == target["meal_id"]
    assert _own_meals(athlete) == 0

    body = _meals_body(_plan(athlete.client))
    target = body["meal_days"][0]["meals"][0]
    target["items"] = [{**items[0], "grams": items[0]["grams"] + 10}, *items[1:]]
    first = _put(athlete.client, "meals", body)
    assert first.status_code == 200, first.text
    copy_id = first.json()["meal_days"][0]["meals"][0]["meal"]["id"]
    assert copy_id != target["meal_id"] and _own_meals(athlete) == 1

    body = _meals_body(first.json())  # re-sends the copy with its own grams
    body["meal_days"][0]["meals"][0]["items"] = target["items"]
    again = _put(athlete.client, "meals", body)
    assert again.status_code == 200, again.text
    assert again.json()["meal_days"][0]["meals"][0]["meal"]["id"] == copy_id
    assert _own_meals(athlete) == 1
    listed = athlete.client.get("/api/v1/meals", params={"limit": 100}).json()["items"]
    assert copy_id in {m["id"] for m in listed}  # the copy is in the athlete's own meals


def test_qa_a_meal_edit_moves_pending_suggestions_to_the_new_version(athlete: Api) -> None:
    plan = _plan(athlete.client)
    planned = plan["training_days"][0]["exercises"][0]
    with Session(athlete.app.state.engine) as session:
        session.add(
            Suggestion(
                athlete_id=_user_id(athlete),
                kind="progression",
                status="pending",
                rule="r",
                reason="r",
                inputs={},
                payload={"planned_exercise_id": planned["id"]},
                planned_exercise_id=uuid.UUID(planned["id"]),
                exercise_id=uuid.UUID(planned["exercise"]["id"]),
                created_at=plan["created_at"],
            )
        )
        session.commit()
    new = _put(athlete.client, "meals", _meals_body(plan)).json()
    with Session(athlete.app.state.engine) as session:
        row = session.scalars(select(Suggestion)).one()
        assert row.status == "pending"
        assert str(row.planned_exercise_id) == new["training_days"][0]["exercises"][0]["id"]


@pytest.fixture
def onboarded(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    assert api.client.post(ONBOARD, json=onboarding()).status_code == 201
    return api


def test_qa_regenerate_moves_todays_logged_meal_to_extras_and_eaten_is_unchanged(
    onboarded: Api,
) -> None:
    day = _day(onboarded.client, THU)
    logged = day["meals"][0]["planned_meal"]
    log = _log(onboarded.client, logged["id"])["meal_log"]
    eaten = _day(onboarded.client, THU)["energy"]["eaten"]
    response = onboarded.client.post(f"{ME}/plan/regenerate", json={"scope": "meals"})
    assert response.status_code == 201, response.text
    after = _day(onboarded.client, THU)
    assert all(m["log"] is None for m in after["meals"])
    assert [e["id"] for e in after["extra_meal_logs"]] == [log["id"]]
    assert after["energy"]["eaten"] == eaten  # counted once, still visible and undoable
