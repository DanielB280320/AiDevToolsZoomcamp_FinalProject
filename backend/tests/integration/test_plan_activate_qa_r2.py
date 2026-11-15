"""QA PR #240 round 2 (D108 activation log): local-midnight boundary, an edit after a
re-activation, and the activation log rows an idempotent "make current" writes."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PlanActivation
from tests.integration.auth_helpers import Api
from tests.integration.test_plan_activate_delete import _activate, _new
from tests.integration.test_plan_activate_history import _keys, _own_meals
from tests.integration.test_plan_editor import (
    _plan,
    athlete,  # noqa: F401  (fixture)
)

THU = "2026-10-22"  # NOW = Thu 09:00 UTC; Europe/Madrid is UTC+2 (CEST) that week
FRI = "2026-10-23"


def _log_rows(api: Api) -> int:
    with Session(api.app.state.engine) as db:
        return int(db.scalar(select(func.count()).select_from(PlanActivation)) or 0)


def test_local_midnight_edit_after_reactivation_and_idempotent_log(
    athlete: Api,  # noqa: F811
) -> None:
    client = athlete.client
    first = _plan(client)
    one = {d: _keys(client, d) for d in (THU, FRI)}

    athlete.clock.advance(hours=1)  # Thu 10:00 UTC: plan 2 with meals of its own
    _new(client, "Second")
    _own_meals(client, first)
    two = {d: _keys(client, d) for d in (THU, FRI)}
    assert all(two[d] and two[d].isdisjoint(one[d]) for d in (THU, FRI))
    assert _log_rows(athlete) == 0

    # Thu 22:30 UTC is Fri 00:30 in Madrid: Thursday (local) ended under plan 2.
    athlete.clock.advance(hours=12, minutes=30)
    assert _activate(client, 1).status_code == 200
    assert _log_rows(athlete) == 1
    assert _keys(client, THU) == two[THU]
    assert _keys(client, FRI) == one[FRI]

    again = _activate(client, 1)  # idempotent: no new log row
    assert again.status_code == 200
    assert _log_rows(athlete) == 1

    # An edit of the re-activated plan writes a new version of plan 1 that is in force from now.
    athlete.clock.advance(hours=2)
    _own_meals(client, first)
    edited = _plan(client)
    assert edited["plan_no"] == 1
    assert edited["version"] == max(first["version"], 3) + 1
    friday = _keys(client, FRI)
    assert friday and friday.isdisjoint(one[FRI]) and friday.isdisjoint(two[FRI])
    assert _keys(client, THU) == two[THU]  # the past day is not touched by the edit
    assert _log_rows(athlete) == 1
