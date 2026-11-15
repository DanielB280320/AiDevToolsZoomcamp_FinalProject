"""QA for PR #237 (D106): the `plan_no` backfill agrees with what the writers assign on realistic
data (two athletes, coach edits, New plan forms with a name and a start date, regenerations),
the migration round-trips repeatedly, earlier snapshots never change after later edits, readers
and writers resolve a mix of stored and null numbers, and `plan_no` is validated."""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.models import Plan
from app.seed import run_seed
from tests.integration.auth_helpers import NOW, Api
from tests.integration.test_coach_dashboard import World, w  # noqa: F401  (fixture)
from tests.integration.test_onboarding import ONBOARD, onboarding
from tests.integration.test_plan_editor import ME, _meals_body, _put, _training_body
from tests.integration.test_user_delete_food_cascade import _alembic

PREVIOUS_HEAD = "b7d2f4a9c613"
BASE = "/api/v1/athletes"


def _plan_of(client: Any, who: str = "me") -> dict[str, Any]:
    r = client.get(f"{BASE}/{who}/plan")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _stored(url: str) -> dict[tuple[uuid.UUID, int], int | None]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT athlete_id, version, plan_no FROM plan"))
            return {(r[0], r[1]): r[2] for r in rows}
    finally:
        engine.dispose()


def test_backfill_reproduces_the_writers_numbers_on_realistic_data(w: World) -> None:  # noqa: F811
    with Session(w.api.app.state.engine) as db:
        run_seed(db)
    ana, bob = w.athlete("Ana"), w.athlete("Bob")
    for who in (ana, bob):
        assert who.client.post(ONBOARD, json=onboarding()).status_code == 201
    a = str(ana.id)
    # plan 1 of ana: coach edits training, ana edits meals, coach regenerates
    coach_edit = _put(w.cleo.client, "training", _training_body(_plan_of(ana.client)), a)
    assert coach_edit.status_code == 200
    assert _put(ana.client, "meals", _meals_body(_plan_of(ana.client))).status_code == 200
    regen = w.cleo.client.post(f"{BASE}/{a}/plan/regenerate", json={"scope": "training"})
    assert regen.status_code == 201
    # plan 2: New plan form, empty, with a start date; then ana regenerates inside it
    start = (NOW.date() - dt.timedelta(days=3)).isoformat()
    r = ana.client.post(f"{ME}/plan", json={"name": "Cut", "start_date": start})
    assert r.status_code == 201, r.text
    assert r.json()["plan_no"] == 2
    assert ana.client.post(f"{ME}/plan/regenerate", json={"scope": "all"}).status_code == 201
    # plan 3: the coach starts a generated plan, then ana edits training twice
    r = w.cleo.client.post(f"{BASE}/{a}/plan", json={"name": "Bulk", "start_from": "generated"})
    assert r.status_code == 201, r.text
    assert r.json()["plan_no"] == 3
    for _ in range(2):
        assert _put(ana.client, "training", _training_body(_plan_of(ana.client))).status_code == 200
    # bob: one plan with three edits
    for _ in range(3):
        assert _put(bob.client, "training", _training_body(_plan_of(bob.client))).status_code == 200

    plans_before = ana.client.get(f"{ME}/plans").json()
    assert [(p["plan_no"], p["changes"], p["name"]) for p in plans_before["items"]] == [
        (3, 2, "Bulk"), (2, 1, "Cut"), (1, 3, None)
    ]  # fmt: skip
    assert [p["changes"] for p in bob.client.get(f"{ME}/plans").json()["items"]] == [3]

    url = w.api.app.state.engine.url.render_as_string(hide_password=False)
    written = _stored(url)
    assert None not in written.values()
    assert {written[(bob.id, v)] for v in range(1, 5)} == {1}

    w.api.app.state.engine.dispose()
    for _ in range(2):  # downgrade/upgrade twice: the backfill is repeatable
        down = _alembic(url, "downgrade", PREVIOUS_HEAD)
        assert down.returncode == 0, down.stderr
        up = _alembic(url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        assert _stored(url) == written
    assert ana.client.get(f"{ME}/plans").json() == plans_before


def test_an_earlier_change_still_opens_the_plan_as_it_was(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    client = api.client
    assert client.post(ONBOARD, json=onboarding()).status_code == 201
    body = _training_body(_plan_of(client))
    body["training_days"] = body["training_days"][:1]  # a real change: keep one day
    assert _put(client, "training", body).status_code == 200
    v2 = client.get(f"{ME}/plan/versions/2").json()
    timeline_before = client.get(f"{ME}/plan/versions", params={"plan_no": 1}).json()["items"]
    assert len(v2["training_days"]) == 1

    assert client.post(f"{ME}/plan/regenerate", json={"scope": "training"}).status_code == 201
    assert client.post(f"{ME}/plan", json={"name": "Next"}).status_code == 201

    later = client.get(f"{ME}/plan/versions/2").json()
    ignore = {"active"}
    assert {k: v for k, v in later.items() if k not in ignore} == {
        k: v for k, v in v2.items() if k not in ignore
    }
    assert later["plan_no"] == 1
    timeline = client.get(f"{ME}/plan/versions", params={"plan_no": 1}).json()["items"]
    assert [(v["version"], v["change"]) for v in timeline[1:]] == [
        (v["version"], v["change"]) for v in timeline_before
    ]
    assert timeline[0]["change"]["kind"] == "regenerated"


def test_mixed_stored_and_null_numbers_resolve_and_writers_continue(api: Api) -> None:
    """v1-v2 written by this release; v3 (New plan) and v4 (edit) by the previous one (null)."""
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    client = api.client
    assert client.post(ONBOARD, json=onboarding()).status_code == 201
    assert _put(client, "training", _training_body(_plan_of(client))).status_code == 200
    assert client.post(f"{ME}/plan", json={"name": "B"}).status_code == 201
    assert _put(client, "meals", _meals_body(_plan_of(client))).status_code == 200
    with Session(api.app.state.engine) as session:
        for plan in session.scalars(select(Plan).where(Plan.version >= 3)):
            plan.plan_no = None
        session.commit()
    versions = client.get(f"{ME}/plan/versions").json()["items"]
    assert [(v["version"], v["plan_no"]) for v in versions] == [(4, 2), (3, 2), (2, 1), (1, 1)]
    assert _plan_of(client)["plan_no"] == 2
    assert _put(client, "training", _training_body(_plan_of(client))).json()["plan_no"] == 2
    assert client.post(f"{ME}/plan", json={"name": "C"}).json()["plan_no"] == 3
    items = client.get(f"{ME}/plans").json()["items"]
    assert [(p["plan_no"], p["changes"], p["active"]) for p in items] == [
        (3, 0, True), (2, 2, False), (1, 1, False)
    ]  # fmt: skip


def test_plan_no_filter_rejects_zero_and_text(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    assert api.client.post(ONBOARD, json=onboarding()).status_code == 201
    for bad in ("0", "-1", "x"):
        r = api.client.get(f"{ME}/plan/versions", params={"plan_no": bad})
        assert r.status_code in (400, 422), (bad, r.status_code)
