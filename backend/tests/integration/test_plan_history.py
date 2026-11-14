"""D106 against real Postgres: versions are grouped into plans. Only onboarding and `createPlan`
start a plan; every other write keeps the plan number. The plan list, the per-plan change
timeline and the access rules (the matrix covers the generated cases for `listPlans`)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Plan
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api
from tests.integration.test_coach_dashboard import World, w  # noqa: F401  (fixture)
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_plan_editor import (
    ME,
    _meals_body,
    _plan,
    _put,
    _training_body,
)
from tests.integration.test_rescale_portions import _profile_edit
from tests.integration.test_rescale_portions import athlete as rescale_athlete  # noqa: F401
from tests.integration.test_suggestions import athlete as suggestion_athlete  # noqa: F401
from tests.integration.test_training_log import _finish, _ids, _log, _session


def _plans(client: Any, who: str = "me") -> list[dict[str, Any]]:
    response = client.get(f"/api/v1/athletes/{who}/plans")
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_schema(body, "PlanList")
    items: list[dict[str, Any]] = body["items"]
    return items


def _versions(client: Any, plan_no: int | None = None, who: str = "me") -> list[dict[str, Any]]:
    params = {} if plan_no is None else {"plan_no": plan_no}
    response = client.get(f"/api/v1/athletes/{who}/plan/versions", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_schema(body, "PlanVersionList")
    items: list[dict[str, Any]] = body["items"]
    return items


def test_every_path_keeps_the_plan_number_and_only_the_new_plan_form_starts_one(
    suggestion_athlete: Api,  # noqa: F811
) -> None:
    api = suggestion_athlete
    client = api.client
    first = _plan(client)
    assert first["plan_no"] == 1
    assert_matches_schema(first, "Plan")
    existing = _versions(client)
    assert {v["plan_no"] for v in existing} == {1}  # the fixture's own history stays plan 1

    edited = _put(client, "training", _training_body(first))
    assert edited.status_code == 200, edited.text
    assert edited.json()["plan_no"] == 1
    meals = _put(client, "meals", _meals_body(_plan(client)))
    assert meals.status_code == 200, meals.text
    assert meals.json()["plan_no"] == 1

    sid, ex, planned_id, _ = _ids(_session(api))
    for n in (1, 2, 3):
        _log(api, sid, exercise_id=ex, planned_exercise_id=planned_id, set_no=n, reps=8,
             weight_kg=50)  # fmt: skip
    (suggestion,) = _finish(api, sid).json()["suggestions"]
    accepted = client.post(f"/api/v1/suggestions/{suggestion['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert _plan(client)["plan_no"] == 1

    (only,) = _plans(client)
    assert (only["plan_no"], only["active"], only["name"]) == (1, True, None)
    assert only["changes"] == len(_versions(client)) - 1 >= 3
    assert only["first_version"] == 1 and only["latest_version"] == only["changes"] + 1
    assert only["last_changed_at"] >= only["created_at"]

    created = client.post(f"{ME}/plan", json={"name": "Second"})
    assert created.status_code == 201, created.text
    assert created.json()["plan_no"] == 2
    again = _put(client, "training", _training_body(_plan(client)))
    assert again.json()["plan_no"] == 2

    items = _plans(client)
    assert [(p["plan_no"], p["active"]) for p in items] == [(2, True), (1, False)]
    assert [p["name"] for p in items] == ["Second", None]
    assert [p["changes"] for p in items] == [1, only["changes"]]
    assert items[0]["source"] == "custom"

    timeline = _versions(client, 1)
    assert [v["version"] for v in timeline] == sorted(
        (v["version"] for v in timeline), reverse=True
    )
    assert len(timeline) == only["changes"] + 1
    kinds = [v["change"]["kind"] for v in timeline]
    assert kinds[-1] == "created"
    assert {"training_edited", "meals_edited", "suggestion_accepted"} <= set(kinds)
    assert all(v["change"]["author_role"] == "athlete" for v in timeline)
    assert all(v["change"]["author"]["role"] == "athlete" for v in timeline)
    assert [v["change"]["kind"] for v in _versions(client, 2)] == ["training_edited", "created_new"]
    assert _versions(client, 99) == []
    assert len(_versions(client)) == sum(p["changes"] + 1 for p in items)
    # F8.2: an older plan stays readable as of any of its versions
    old = client.get(f"{ME}/plan/versions/1")
    assert old.status_code == 200 and old.json()["plan_no"] == 1
    assert_matches_schema(old.json(), "Plan")


def test_regenerate_and_a_portion_rescale_are_changes_inside_the_plan_and_generated_starts_one(
    rescale_athlete: Api,  # noqa: F811
) -> None:
    client = rescale_athlete.client
    assert _profile_edit(rescale_athlete).status_code == 200
    (plan,) = _plans(client)
    assert (plan["plan_no"], plan["changes"], plan["active"]) == (1, 1, True)
    assert _versions(client, 1)[0]["change"]["kind"] == "portions_rescaled"
    regenerated = client.post(f"{ME}/plan/regenerate", json={"scope": "meals"})
    assert regenerated.status_code == 201, regenerated.text
    assert regenerated.json()["plan_no"] == 1
    assert _versions(client, 1)[0]["change"]["kind"] == "regenerated"

    generated = client.post(f"{ME}/plan", json={"name": "Third", "start_from": "generated"})
    assert generated.status_code == 201, generated.text
    assert generated.json()["plan_no"] == 2
    assert client.post(f"{ME}/plan/regenerate").json()["plan_no"] == 2
    items = _plans(client)
    assert [(p["plan_no"], p["changes"], p["active"]) for p in items] == [
        (2, 1, True), (1, 2, False)
    ]  # fmt: skip
    assert items[0]["source"] == "generated" and items[0]["name"] == "Third"
    assert [v["change"]["kind"] for v in _versions(client, 2)] == ["regenerated", "created_new"]


def test_a_row_without_a_plan_number_follows_the_preceding_version(api: Api) -> None:
    """Rows the previous release writes have `plan_no` null: same plan, unless `created_new`."""
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    assert api.client.post(ONBOARD, json=onboarding()).status_code == 201
    client = api.client
    assert _put(client, "training", _training_body(_plan(client))).status_code == 200
    assert client.post(f"{ME}/plan", json={"name": "B"}).status_code == 201
    assert _put(client, "training", _training_body(_plan(client))).status_code == 200
    with Session(api.app.state.engine) as session:
        for plan in session.scalars(select(Plan)):
            plan.plan_no = None
        session.commit()
    assert [(v["version"], v["plan_no"]) for v in _versions(client)] == [
        (4, 2), (3, 2), (2, 1), (1, 1)
    ]  # fmt: skip
    # a write after that continues from the resolved number
    assert _put(client, "training", _training_body(_plan(client))).json()["plan_no"] == 2
    assert client.post(f"{ME}/plan", json={"name": "C"}).json()["plan_no"] == 3
    assert [p["plan_no"] for p in _plans(client)] == [3, 2, 1]


def test_the_linked_coach_sees_plans_and_is_the_author_of_their_changes(w: World) -> None:  # noqa: F811
    with Session(w.api.app.state.engine) as db:
        run_seed(db)
    ana = w.athlete("Ana")
    assert ana.client.post(ONBOARD, json=onboarding()).status_code == 201
    plan = _plan(ana.client)
    edit = _put(w.cleo.client, "training", _training_body(plan), str(ana.id))
    assert edit.status_code == 200, edit.text
    assert [p["changes"] for p in _plans(w.cleo.client, str(ana.id))] == [1]
    assert _plans(w.cleo.client, str(ana.id)) == _plans(ana.client)
    timeline = _versions(w.cleo.client, 1, str(ana.id))
    assert timeline == _versions(ana.client, 1)
    assert timeline[0]["change"]["author_role"] == "coach"
    assert timeline[0]["change"]["author"]["role"] == "coach"
    assert timeline[1]["change"]["author_role"] == "athlete"
