"""#24 plan persistence against real Postgres: versioning, the one-active constraint, the
`PlanChange` audit row, snapshots ("edits never change the past") and `GET /athletes/{id}/plan`."""

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Exercise, Plan, PlanChange, PlannedExercise, TrainingDay, User
from app.seed import run_seed
from app.services.plans import NewPlannedExercise, NewTrainingDay, create_plan_version
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api, problem

LATER = NOW + dt.timedelta(days=7)


@pytest.fixture
def seeded(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    return api


def _user_id(api: Api, email: str = "ana@x.test") -> uuid.UUID:
    with Session(api.app.state.engine) as session:
        return session.scalars(select(User.id).where(User.email == email)).one()


def _exercise_ids(api: Api) -> dict[str, uuid.UUID]:
    with Session(api.app.state.engine) as session:
        return {
            e.type: e.id
            for e in session.scalars(select(Exercise).where(Exercise.owner_id.is_(None)))
        }


def _days(api: Api, name: str = "Push") -> list[NewTrainingDay]:
    ex = _exercise_ids(api)
    return [
        # Deliberately not in weekday order: the response must sort Monday -> Sunday.
        NewTrainingDay(
            "fri",
            f"{name} B",
            [NewPlannedExercise(ex["timed"], 3, 60, "manual", 0, target_seconds=45)],
        ),
        NewTrainingDay(
            "mon",
            name,
            [
                NewPlannedExercise(
                    ex["strength"],
                    4,
                    90,
                    "linear",
                    2.5,
                    reps_min=8,
                    reps_max=8,
                    target_weight_kg=60.0,
                ),
                NewPlannedExercise(
                    ex["bodyweight"],
                    3,
                    90,
                    "double",
                    0,
                    reps_min=8,
                    reps_max=12,
                ),
            ],
        ),
    ]


def _create(
    api: Api,
    *,
    source: str = "generated",
    name: str = "Push",
    author: uuid.UUID | None = None,
    now: dt.datetime = NOW,
) -> Plan:
    uid = _user_id(api)
    with Session(api.app.state.engine) as session:
        plan = create_plan_version(
            session,
            athlete_id=uid,
            author_id=author or uid,
            source=source,
            days=_days(api, name),
            now=now,
        )
        session.commit()
        session.refresh(plan)
        session.expunge(plan)
    return plan


@pytest.fixture
def athlete(seeded: Api) -> Api:
    assert seeded.signup().status_code == 201
    return seeded


# ───────────── versioning ─────────────


def test_versions_increment_and_only_the_latest_is_active(athlete: Api) -> None:
    first = _create(athlete)
    second = _create(athlete, source="custom", now=LATER)
    assert (first.version, second.version) == (1, 2)
    assert (first.revision, second.revision) == (0, 0)
    with Session(athlete.app.state.engine) as session:
        rows = session.scalars(select(Plan).order_by(Plan.version)).all()
        assert [(p.version, p.active, p.source) for p in rows] == [
            (1, False, "generated"),
            (2, True, "custom"),
        ]
        assert rows[1].created_at == LATER and rows[1].updated_at == LATER


def test_database_rejects_a_second_active_plan(athlete: Api) -> None:
    _create(athlete)
    uid = _user_id(athlete)
    with Session(athlete.app.state.engine) as session:
        session.add(
            Plan(
                athlete_id=uid,
                version=2,
                source="custom",
                active=True,
                created_by=uid,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        with pytest.raises(IntegrityError, match="uq_plan_one_active_per_athlete"):
            session.commit()


def test_database_rejects_duplicate_versions_but_allows_many_inactive(athlete: Api) -> None:
    _create(athlete)
    uid = _user_id(athlete)
    with Session(athlete.app.state.engine) as session:
        session.add(
            Plan(
                athlete_id=uid,
                version=1,
                source="custom",
                active=False,
                created_by=uid,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        with pytest.raises(IntegrityError, match="uq_plan_athlete_id_version"):
            session.commit()


def test_each_athlete_has_their_own_version_sequence(athlete: Api) -> None:
    _create(athlete)
    other = athlete.new_client()
    assert (
        other.post(
            "/api/v1/auth/signup",
            json={
                "email": "bo@x.test",
                "password": "correct-horse-battery",
                "display_name": "Bo",
                "role": "athlete",
                "birth_date": "1990-01-01",
                "units": "metric",
                "timezone": "UTC",
                "accept_disclaimer": True,
            },
        ).status_code
        == 201
    )
    bo = _user_id(athlete, "bo@x.test")
    with Session(athlete.app.state.engine) as session:
        plan = create_plan_version(
            session,
            athlete_id=bo,
            author_id=bo,
            source="generated",
            days=_days(athlete),
            now=NOW,
        )
        session.commit()
        assert plan.version == 1
        assert (
            session.scalar(select(Plan.active).where(Plan.athlete_id == _user_id(athlete))) is True
        )


def test_failed_creation_rolls_back_and_keeps_the_previous_version_active(athlete: Api) -> None:
    _create(athlete)
    uid = _user_id(athlete)
    bad = [NewTrainingDay("mon", "X", [NewPlannedExercise(uuid.uuid4(), 3, 90, "linear", 2.5)])]
    with Session(athlete.app.state.engine) as session:
        with pytest.raises(IntegrityError):
            create_plan_version(
                session, athlete_id=uid, author_id=uid, source="generated", days=bad, now=LATER
            )
        session.rollback()
    with Session(athlete.app.state.engine) as session:
        rows = session.scalars(select(Plan)).all()
        assert [(p.version, p.active) for p in rows] == [(1, True)]


# ───────────── stored fields, audit row, past is unchanged ─────────────


def test_every_contract_field_is_stored(athlete: Api) -> None:
    plan = _create(athlete)
    with Session(athlete.app.state.engine) as session:
        days = session.scalars(
            select(TrainingDay).where(TrainingDay.plan_id == plan.id).order_by(TrainingDay.position)
        ).all()
        assert [(d.weekday, d.name, d.position) for d in days] == [
            ("fri", "Push B", 0),
            ("mon", "Push", 1),
        ]
        monday = days[1]
        first = monday.exercises[0]
        assert (first.sets, first.reps_min, first.reps_max, first.target_weight_kg) == (
            4,
            8,
            8,
            60.0,
        )
        assert (first.rest_seconds, first.rule, first.increment_kg) == (90, "linear", 2.5)
        assert first.deload_enabled is True and first.target_seconds is None and first.position == 0
        assert monday.exercises[1].target_weight_kg is None  # calibration
        assert days[0].exercises[0].target_seconds == 45


def test_creating_a_version_writes_one_plan_change_with_author_and_utc_time(athlete: Api) -> None:
    uid = _user_id(athlete)
    plan = _create(athlete, now=LATER)
    with Session(athlete.app.state.engine) as session:
        changes = session.scalars(select(PlanChange).where(PlanChange.plan_id == plan.id)).all()
        assert len(changes) == 1
        assert changes[0].author_id == uid
        assert changes[0].created_at == LATER
        assert changes[0].created_at.utcoffset() == dt.timedelta(0)
        assert changes[0].change["kind"] == "created"


def test_plan_edits_never_change_the_past(athlete: Api) -> None:
    """A new version leaves the earlier version's rows untouched (F8.2, rule 7)."""
    first = _create(athlete, name="Push")

    def snapshot() -> list[tuple[Any, ...]]:
        with Session(athlete.app.state.engine) as session:
            rows = session.execute(
                text(
                    "SELECT d.id, d.weekday, d.name, e.id, e.sets, e.reps_min, e.target_weight_kg,"
                    " e.rule FROM training_day d"
                    " JOIN planned_exercise e ON e.training_day_id = d.id"
                    " WHERE d.plan_id = :p ORDER BY d.id, e.id"
                ),
                {"p": first.id},
            )
            return [tuple(r) for r in rows]

    before = snapshot()
    assert before
    _create(athlete, source="custom", name="Totally different", now=LATER)
    assert snapshot() == before
    with Session(athlete.app.state.engine) as session:
        old = session.get(Plan, first.id)
        assert old is not None
        assert (old.version, old.source, old.revision, old.created_at) == (1, "generated", 0, NOW)
        assert old.active is False


def test_catalog_exercises_in_use_cannot_be_deleted(athlete: Api) -> None:
    plan = _create(athlete)
    with Session(athlete.app.state.engine) as session:
        used = session.scalars(
            select(PlannedExercise.exercise_id)
            .join(TrainingDay)
            .where(TrainingDay.plan_id == plan.id)
        ).first()
        with pytest.raises(IntegrityError):
            session.execute(text("DELETE FROM exercise WHERE id = :i"), {"i": used})


# ───────────── GET /athletes/{id}/plan ─────────────


def test_get_plan_returns_the_active_version_matching_the_contract(athlete: Api) -> None:
    _create(athlete, name="Old")
    plan = _create(athlete, source="custom", name="New", now=LATER)
    for path in ("me", str(_user_id(athlete))):
        response = athlete.client.get(f"/api/v1/athletes/{path}/plan")
        assert response.status_code == 200, response.text
        body = response.json()
        assert_matches_schema(body, "Plan")
        assert body["id"] == str(plan.id) and body["version"] == 2 and body["active"] is True
        assert body["source"] == "custom" and body["revision"] == 0
        assert body["meal_days"] == [] and body["warnings"] == []
        assert body["created_by"]["display_name"] == "Ana"
        assert [d["weekday"] for d in body["training_days"]] == ["mon", "fri"]
        assert body["training_days"][0]["name"] == "New"
        assert body["training_days"][0]["edited_by"] is None
        exercises = body["training_days"][0]["exercises"]
        assert [e["order"] for e in exercises] == [0, 1]
        assert exercises[0]["target_weight_kg"] == 60.0 and exercises[0]["calibration_hint"] is None
        assert exercises[1]["target_weight_kg"] is None and exercises[1]["calibration_hint"]
        assert body["training_days"][0]["estimated_minutes"] > 0


def test_no_plan_yet_is_404_not_onboarded(athlete: Api) -> None:
    problem(athlete.client.get("/api/v1/athletes/me/plan"), 404, "not_onboarded")


def test_without_a_session_is_401(athlete: Api) -> None:
    problem(athlete.new_client().get("/api/v1/athletes/me/plan"), 401, "not_authenticated")


def test_stranger_and_unknown_ids_are_both_403(athlete: Api) -> None:
    _create(athlete)
    stranger = athlete.new_client()
    assert (
        stranger.post(
            "/api/v1/auth/signup",
            json={
                "email": "eve@x.test",
                "password": "correct-horse-battery",
                "display_name": "Eve",
                "role": "athlete",
                "birth_date": "1990-01-01",
                "units": "metric",
                "timezone": "UTC",
                "accept_disclaimer": True,
            },
        ).status_code
        == 201
    )
    ana = _user_id(athlete)
    unknown = stranger.get(f"/api/v1/athletes/{uuid.uuid4()}/plan")
    other = stranger.get(f"/api/v1/athletes/{ana}/plan")
    problem(unknown, 403, "not_linked")
    problem(other, 403, "not_linked")
    assert unknown.json()["detail"] == other.json()["detail"]  # indistinguishable (D41)


def test_unlinked_coach_gets_403(athlete: Api) -> None:
    _create(athlete)
    coach = athlete.new_client()
    assert (
        coach.post(
            "/api/v1/auth/signup",
            json={
                "email": "cy@x.test",
                "password": "correct-horse-battery",
                "display_name": "Cy",
                "role": "coach",
                "birth_date": "1985-01-01",
                "units": "metric",
                "timezone": "UTC",
                "accept_disclaimer": True,
            },
        ).status_code
        == 201
    )
    problem(coach.get(f"/api/v1/athletes/{_user_id(athlete)}/plan"), 403, "not_linked")


def test_malformed_athlete_id_is_400(athlete: Api) -> None:
    problem(athlete.client.get("/api/v1/athletes/not-a-uuid/plan"), 400, "bad_request")
