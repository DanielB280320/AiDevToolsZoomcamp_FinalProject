# ruff: noqa: S608  (table names come from information_schema in this test)
"""QA for #148 / D69: deletion through the real onboarding path (not hand-inserted rows) and
the API view of a plan whose author/editor was deleted (owner reads `created_by: null`)."""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Plan, TrainingDay, User
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem, signup_body
from tests.integration.test_onboarding import ONBOARD, PLAN, metric_body, onboarding, profile_body


def _uid(api: Api, email: str) -> uuid.UUID:
    with Session(api.app.state.engine) as session:
        return session.scalars(select(User.id).where(User.email == email)).one()


def _table_counts(api: Api) -> dict[str, int]:
    with api.app.state.engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                " AND table_type = 'BASE TABLE' AND table_name <> 'alembic_version'"
            )
        ).scalars()
        return {
            t: int(conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one()) for t in tables
        }


def _onboard(client: TestClient) -> None:
    response = client.post(ONBOARD, json=onboarding(profile_body(), metric_body()))
    assert response.status_code == 201, response.text


def test_deleting_a_really_onboarded_athlete_leaves_no_rows_in_any_table(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    # A bystander athlete, onboarded too, whose rows must survive.
    assert api.signup(email="bob@x.test").status_code == 201
    _onboard(api.client)
    baseline = _table_counts(api)

    ana = api.new_client()
    assert ana.post("/api/v1/auth/signup", json={**_signup("ana@x.test")}).status_code == 201
    _onboard(ana)
    ana_id = _uid(api, "ana@x.test")
    with api.app.state.engine.connect() as conn:
        changes = conn.execute(
            text(
                "SELECT count(*) FROM plan_change c JOIN plan p ON p.id = c.plan_id"
                " WHERE p.athlete_id = :a AND c.author_id = :a"
            ),
            {"a": ana_id},
        ).scalar_one()
    assert changes >= 1  # the original failure mode from #148

    with api.app.state.engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": ana_id})

    assert _table_counts(api) == baseline


def _signup(email: str) -> dict[str, Any]:
    return signup_body(email=email)


def test_owner_reads_plan_with_null_author_after_coach_deleted_and_stranger_is_still_403(
    api: Api,
) -> None:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    _onboard(api.client)
    coach_client = api.new_client()
    assert (
        coach_client.post("/api/v1/auth/signup", json=_signup("coach@x.test") | {"role": "coach"})
    ).status_code == 201
    ana_id, coach_id = _uid(api, "ana@x.test"), _uid(api, "coach@x.test")
    # No coach-link/edit API yet: attribute the active plan, its days and changes to the coach.
    with Session(api.app.state.engine) as session:
        plan = session.scalars(
            select(Plan).where(Plan.athlete_id == ana_id, Plan.active.is_(True))
        ).one()
        plan.created_by = coach_id
        for day in session.scalars(select(TrainingDay).where(TrainingDay.plan_id == plan.id)):
            day.edited_by = coach_id
        session.execute(
            text("UPDATE meal_day SET edited_by = :c WHERE plan_id = :p"),
            {"c": coach_id, "p": plan.id},
        )
        session.execute(
            text("UPDATE plan_change SET author_id = :c WHERE plan_id = :p"),
            {"c": coach_id, "p": plan.id},
        )
        session.commit()
    before = api.client.get(PLAN)
    assert before.status_code == 200
    assert before.json()["created_by"]["id"] == str(coach_id)

    with api.app.state.engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": coach_id})

    after = api.client.get(PLAN)
    assert after.status_code == 200, after.text
    body = after.json()
    assert_matches_schema(body, "Plan")
    assert body["created_by"] is None
    assert all(d["edited_by"] is None for d in body["training_days"])
    assert all(d["edited_by"] is None for d in body["meal_days"])
    assert body["training_days"] == [
        {**d, "edited_by": None} for d in before.json()["training_days"]
    ]

    stranger = api.new_client()
    assert stranger.post("/api/v1/auth/signup", json=_signup("eve@x.test")).status_code == 201
    problem(stranger.get(f"/api/v1/athletes/{ana_id}/plan"), 403, "not_linked")


def test_no_foreign_key_to_users_lacks_an_on_delete_rule(api: Api) -> None:
    """Catalog check at head: every FK to users.id cascades or sets null (D66, D69)."""
    with api.app.state.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conrelid::regclass::text, conname, confdeltype FROM pg_constraint"
                " WHERE contype = 'f' AND confrelid = 'users'::regclass"
            )
        ).all()
    assert rows
    blocking = sorted((t, n) for t, n, rule in rows if rule not in ("c", "n"))
    assert blocking == []
