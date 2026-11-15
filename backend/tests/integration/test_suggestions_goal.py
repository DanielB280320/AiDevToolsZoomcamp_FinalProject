"""D107 goal-driven progression through the finish hook against real Postgres: the plan's training
goal decides hold vs raise, the athlete's age sizes the step, the suggestion stays pending, and
the age is never stored with it."""

import datetime as dt
import json
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Plan, PlannedExercise, User
from tests.integration.auth_helpers import Api
from tests.integration.test_suggestions import (  # noqa: F401  (athlete is a fixture)
    _pending_for,
    _perform,
    athlete,
)
from tests.integration.test_training_log import BASE, FRI, THU


def _plan_rows(api: Api, **values: Any) -> None:
    with Session(api.app.state.engine) as session:
        session.execute(update(Plan).values(**values))
        session.commit()


def _planned(api: Api, **values: Any) -> None:
    with Session(api.app.state.engine) as session:
        session.execute(update(PlannedExercise).values(**values))
        session.commit()


def _only(api: Api, sid: str) -> dict[str, Any]:
    (suggestion,) = _pending_for(api, sid)
    return suggestion


def test_the_default_goal_raises_the_weight_when_the_target_reps_are_met(athlete: Api) -> None:  # noqa: F811
    suggestion = _only(athlete, _perform(athlete, THU, reps=8))
    assert suggestion["status"] == "pending"  # never auto-applied
    assert suggestion["payload"]["proposed"]["target_weight_kg"] > 50.0
    assert suggestion["inputs"]["goal"] == "hypertrophy"  # plan without a goal: profile default


@pytest.mark.parametrize("goal", ["maintenance", "cutting"])
def test_maintenance_and_cutting_hold_the_weight(athlete: Api, goal: str) -> None:  # noqa: F811
    _plan_rows(athlete, training_goal=goal)
    suggestion = _only(athlete, _perform(athlete, THU, reps=8))
    assert suggestion["payload"]["proposed"]["target_weight_kg"] == 50.0
    assert suggestion["inputs"]["goal"] == goal
    assert suggestion["status"] == "pending"
    assert athlete.client.post(f"{BASE}/suggestions/{suggestion['id']}/reject").status_code == 200


def test_inside_the_range_adds_reps_and_all_at_max_goes_heavier(athlete: Api) -> None:  # noqa: F811
    _planned(athlete, rule="double", reps_min=8, reps_max=12)
    _plan_rows(athlete, training_goal="hypertrophy")
    reps = _only(athlete, _perform(athlete, THU, reps=10))
    assert reps["payload"]["proposed"]["target_weight_kg"] == 50.0
    assert reps["payload"]["proposed"]["reps_min"] == 11
    heavier = _only(athlete, _perform(athlete, FRI, reps=12))
    assert heavier["payload"]["proposed"]["target_weight_kg"] > 50.0
    assert heavier["payload"]["proposed"]["reps_min"] == 8


def test_an_older_athlete_gets_a_smaller_step_and_the_age_is_not_stored(athlete: Api) -> None:  # noqa: F811
    _planned(athlete, rule="double", reps_min=8, reps_max=12, target_weight_kg=200.0)
    _plan_rows(athlete, training_goal="strength")
    with Session(athlete.app.state.engine) as session:
        session.execute(update(User).values(birth_date=dt.date(1996, 1, 1)))
        session.commit()
    young = _only(athlete, _perform(athlete, THU, reps=12, weight=200.0))
    with Session(athlete.app.state.engine) as session:
        session.execute(update(User).values(birth_date=dt.date(1950, 1, 1)))
        session.commit()
    older = _only(athlete, _perform(athlete, FRI, reps=12, weight=200.0))
    young_step = young["payload"]["proposed"]["target_weight_kg"] - 200.0
    older_step = older["payload"]["proposed"]["target_weight_kg"] - 200.0
    assert young_step > older_step > 0
    for suggestion in (young, older):
        stored = json.dumps(suggestion["inputs"])
        assert "age_years" not in stored and "birth" not in stored
        assert suggestion["inputs"]["step_factors"]["age"] in (1.0, 0.55)
