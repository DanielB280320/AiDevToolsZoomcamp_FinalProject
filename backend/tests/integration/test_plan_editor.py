"""#39 F8 plan editor API against real Postgres: versioned custom edits (training and meals),
`PlanChange` rows, F8.1 (the past never changes), F8.2 (regenerate, versions stay readable),
F8.4 authorization (owner / unlinked coach / stranger), optimistic concurrency and D73 (logged
meals keep showing their log after a same-day edit)."""

import copy
import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BodyMetric,
    Exercise,
    Meal,
    MealItem,
    Plan,
    PlanChange,
    SetLog,
    Suggestion,
    TrainingSession,
    User,
)
from app.seed import run_seed
from app.services.plans import (
    NewMealDay,
    NewPlannedExercise,
    NewPlannedMeal,
    NewTrainingDay,
    create_plan_version,
)
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api, problem

THU = "2026-10-22"  # NOW is Thursday 2026-10-22 09:00 UTC
FRI = "2026-10-23"
LAST_THU = "2026-10-15"
BASE = "/api/v1"
ME = f"{BASE}/athletes/me"
PLAN_CREATED = NOW - dt.timedelta(days=60)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SLOTS = ("breakfast", "lunch", "dinner")


def _seed_athlete(api: Api, email: str = "ana@x.test") -> None:
    assert api.signup(email=email).status_code == 201
    with Session(api.app.state.engine) as session:
        run_seed(session)
        uid = session.scalars(select(User.id).where(User.email == email)).one()
        strength = session.scalars(
            select(Exercise).where(Exercise.owner_id.is_(None), Exercise.type == "strength")
        ).first()
        timed = session.scalars(
            select(Exercise).where(Exercise.owner_id.is_(None), Exercise.type == "timed")
        ).first()
        picked = list(
            session.scalars(select(Meal).where(Meal.owner_id.is_(None)).order_by(Meal.name))
        )[:4]
        assert strength is not None and timed is not None and len(picked) == 4
        create_plan_version(
            session,
            athlete_id=uid,
            author_id=uid,
            source="generated",
            days=[
                NewTrainingDay(
                    w,
                    f"Day {w}",
                    [
                        NewPlannedExercise(
                            strength.id,
                            3,
                            90,
                            "linear",
                            2.5,
                            reps_min=8,
                            reps_max=8,
                            target_weight_kg=50.0,
                        ),
                        NewPlannedExercise(timed.id, 1, 60, "manual", 0, target_seconds=600),
                    ],
                )
                for w in ("mon", "thu", "fri")
            ],
            meal_days=[
                NewMealDay(
                    w,
                    [NewPlannedMeal(s, m.id, 1.0) for s, m in zip(SLOTS, picked[:3], strict=True)],
                )
                for w in WEEKDAYS
            ],
            now=PLAN_CREATED,
        )
        session.add(
            BodyMetric(user_id=uid, date=dt.date(2026, 9, 1), weight_kg=80.0, created_at=NOW)
        )
        session.commit()


@pytest.fixture
def athlete(api: Api) -> Api:
    _seed_athlete(api)
    return api


def _plan(client: TestClient) -> dict[str, Any]:
    response = client.get(f"{ME}/plan")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _training_body(plan: dict[str, Any]) -> dict[str, Any]:
    """The `TrainingPlanUpdate` that re-sends `plan` unchanged (ids kept)."""
    return {
        "revision": plan["revision"],
        "training_days": [
            {
                "id": d["id"],
                "weekday": d["weekday"],
                "name": d["name"],
                "exercises": [
                    {
                        "id": e["id"],
                        "exercise_id": e["exercise"]["id"],
                        "sets": e["sets"],
                        "reps_min": e["reps_min"],
                        "reps_max": e["reps_max"],
                        "target_weight_kg": e["target_weight_kg"],
                        "target_seconds": e["target_seconds"],
                        "rest_seconds": e["rest_seconds"],
                        "rule": e["rule"],
                        "increment_kg": e["increment_kg"],
                        "deload_enabled": e["deload_enabled"],
                    }
                    for e in d["exercises"]
                ],
            }
            for d in plan["training_days"]
        ],
    }


def _meals_body(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision": plan["revision"],
        "meal_days": [
            {
                "weekday": d["weekday"],
                "meals": [
                    {
                        "id": m["id"],
                        "slot": m["slot"],
                        "meal_id": m["meal"]["id"],
                        "portion_factor": m["portion_factor"],
                    }
                    for m in d["meals"]
                ],
            }
            for d in plan["meal_days"]
        ],
    }


def _put(client: TestClient, kind: str, body: dict[str, Any], athlete: str = "me") -> Any:
    return client.put(f"{BASE}/athletes/{athlete}/plan/{kind}", json=body)


def _day(client: TestClient, day: str = THU) -> dict[str, Any]:
    response = client.get(f"{ME}/days/{day}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_matches_schema(body, "DayView")
    return body


def _targets(session: dict[str, Any]) -> list[Any]:
    """Planned targets and logged values of every set (ids of the plan rows excluded)."""
    return [
        (
            e["exercise"]["id"],
            [
                (
                    s["target_reps"],
                    s["target_weight_kg"],
                    s["target_seconds"],
                    s["log"] and s["log"]["id"],
                )
                for s in e["sets"]
            ],
        )
        for e in session["exercises"]
    ]


def _user_id(api: Api, email: str = "ana@x.test") -> uuid.UUID:
    with Session(api.app.state.engine) as session:
        return session.scalars(select(User.id).where(User.email == email)).one()


# ───────────── training edit: version, source, PlanChange (F8.3) ─────────────


def test_a_training_edit_stores_a_new_custom_version_and_a_plan_change(athlete: Api) -> None:
    before = _plan(athlete.client)
    body = _training_body(before)
    body["training_days"][0]["exercises"][0]["sets"] = 5
    body["training_days"][0]["name"] = "Heavy"
    response = _put(athlete.client, "training", body)
    assert response.status_code == 200, response.text
    new = response.json()
    assert_matches_schema(new, "Plan")
    assert (new["version"], new["source"], new["active"], new["revision"]) == (
        2,
        "custom",
        True,
        before["revision"] + 1,
    )
    day = new["training_days"][0]
    assert day["name"] == "Heavy" and day["exercises"][0]["sets"] == 5
    assert day["edited_by"]["display_name"] == "Ana"
    # Untouched days keep their label, so only the edited one says "edited by".
    assert [d["edited_by"] for d in new["training_days"][1:]] == [None, None]
    assert new["meal_days"] and len(new["meal_days"]) == 7  # meals carried over
    assert _plan(athlete.client)["version"] == 2

    with Session(athlete.app.state.engine) as session:
        plan = session.scalars(select(Plan).where(Plan.version == 2)).one()
        change = session.scalars(select(PlanChange).where(PlanChange.plan_id == plan.id)).one()
        assert change.author_id == _user_id(athlete) and change.author_role == "athlete"
        assert change.created_at == NOW
        assert change.change["kind"] == "training_edited"


def test_f8_2_previous_versions_stay_listable_and_readable(athlete: Api) -> None:
    first = _plan(athlete.client)
    body = _training_body(first)
    body["training_days"][0]["exercises"][0]["sets"] = 5
    assert _put(athlete.client, "training", body).status_code == 200
    body = _training_body(_plan(athlete.client))
    body["training_days"][1]["name"] = "Again"
    assert _put(athlete.client, "training", body).status_code == 200

    listed = athlete.client.get(f"{ME}/plan/versions")
    assert listed.status_code == 200
    assert_matches_schema(listed.json(), "PlanVersionList")
    items = listed.json()["items"]
    assert [(v["version"], v["source"], v["active"]) for v in items] == [
        (3, "custom", True),
        (2, "custom", False),
        (1, "generated", False),
    ]
    old = athlete.client.get(f"{ME}/plan/versions/1")
    assert old.status_code == 200
    assert_matches_schema(old.json(), "Plan")
    assert old.json()["id"] == first["id"] and old.json()["active"] is False
    assert old.json()["training_days"][0]["exercises"][0]["sets"] == 3
    missing = athlete.client.get(f"{ME}/plan/versions/9")
    problem(missing, 404, "not_found")


def test_stale_revision_is_a_conflict_and_changes_nothing(athlete: Api) -> None:
    first = _plan(athlete.client)
    body = _training_body(first)
    body["training_days"][0]["exercises"][0]["sets"] = 4
    assert _put(athlete.client, "training", body).status_code == 200
    stale = _put(athlete.client, "training", body)  # still carries the old revision
    problem(stale, 409, "plan_revision_conflict")
    meals = _meals_body(first)
    problem(_put(athlete.client, "meals", meals), 409, "plan_revision_conflict")
    assert _plan(athlete.client)["version"] == 2


# ───────────── F8.1 the past never changes ─────────────


def test_f8_1_a_finished_session_keeps_its_targets_and_a_future_one_follows_the_edit(
    athlete: Api,
) -> None:
    thursday = _day(athlete.client)["session"]
    sid = thursday["id"]
    planned = thursday["exercises"][0]["planned_exercise_id"]
    exercise = thursday["exercises"][0]["exercise"]["id"]
    for n in (1, 2, 3):
        logged = athlete.client.post(
            f"{BASE}/sessions/{sid}/sets",
            json={"exercise_id": exercise, "set_no": n, "reps": 8, "weight_kg": 50},
        )
        assert logged.status_code in (200, 201), logged.text
    assert athlete.client.post(f"{BASE}/sessions/{sid}/finish", json=None).status_code == 200
    friday = _day(athlete.client, FRI)["session"]  # materialised on version 1, still untouched
    assert friday["plan_version"] == 1
    snapshot = _day(athlete.client)["session"]
    plan = _plan(athlete.client)
    old_plan_id = plan["id"]

    body = _training_body(plan)
    for d in body["training_days"]:
        first = d["exercises"][0]
        first.update(sets=5, reps_min=12, reps_max=12, target_weight_kg=80)
    assert _put(athlete.client, "training", body).status_code == 200

    after = _day(athlete.client)["session"]
    assert after["plan_version"] == 1 and after["status"] == "done"
    assert _targets(after) == _targets(snapshot)
    assert after["exercises"][0]["planned_exercise_id"] == planned
    with Session(athlete.app.state.engine) as session:
        row = session.get(TrainingSession, uuid.UUID(sid))
        assert row is not None and str(row.plan_id) == old_plan_id
        logs = session.scalars(select(SetLog).where(SetLog.session_id == row.id)).all()
        assert {(log.target_reps, log.target_weight_kg) for log in logs} == {(8, 50.0)}

    moved = _day(athlete.client, FRI)["session"]
    assert moved["id"] == friday["id"] and moved["plan_version"] == 2
    assert moved["exercises"][0]["reps_min"] == 12


def test_removing_a_training_day_drops_its_untouched_future_session_only(athlete: Api) -> None:
    friday = _day(athlete.client, FRI)["session"]
    assert friday is not None
    plan = _plan(athlete.client)
    body = _training_body(plan)
    body["training_days"] = [d for d in body["training_days"] if d["weekday"] != "fri"]
    assert _put(athlete.client, "training", body).status_code == 200
    assert _day(athlete.client, FRI)["session"] is None
    assert [d["weekday"] for d in _plan(athlete.client)["training_days"]] == ["mon", "thu"]
    # Nothing else was touched: the other weekday is still planned from the new version.
    assert _day(athlete.client, THU)["session"]["plan_version"] == 2


def test_a_pending_suggestion_follows_its_exercise_or_is_rejected_when_it_goes(
    athlete: Api,
) -> None:
    plan = _plan(athlete.client)
    keep, drop = plan["training_days"][0]["exercises"]
    with Session(athlete.app.state.engine) as session:
        uid = _user_id(athlete)
        for planned in (keep, drop):
            session.add(
                Suggestion(
                    athlete_id=uid,
                    kind="progression",
                    status="pending",
                    rule="r",
                    reason="r",
                    inputs={},
                    payload={"planned_exercise_id": planned["id"]},
                    planned_exercise_id=uuid.UUID(planned["id"]),
                    exercise_id=uuid.UUID(planned["exercise"]["id"]),
                    created_at=NOW,
                )
            )
        session.commit()
    body = _training_body(plan)
    body["training_days"][0]["exercises"] = body["training_days"][0]["exercises"][:1]
    new = _put(athlete.client, "training", body).json()
    with Session(athlete.app.state.engine) as session:
        rows = {
            str(s.exercise_id): s
            for s in session.scalars(select(Suggestion).order_by(Suggestion.created_at))
        }
        kept = rows[keep["exercise"]["id"]]
        gone = rows[drop["exercise"]["id"]]
        assert kept.status == "pending"
        assert str(kept.planned_exercise_id) == new["training_days"][0]["exercises"][0]["id"]
        assert gone.status == "rejected" and gone.decided_by == uid


# ───────────── validation ─────────────


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda b: b["training_days"].append(copy.deepcopy(b["training_days"][0])), "duplicate"),
        (lambda b: b["training_days"][0].update(id=str(uuid.uuid4())), "unknown_id"),
        (
            lambda b: b["training_days"][0]["exercises"][0].update(id=str(uuid.uuid4())),
            "unknown_id",
        ),
        (
            lambda b: b["training_days"][0]["exercises"][0].update(exercise_id=str(uuid.uuid4())),
            "unknown_exercise",
        ),
        (lambda b: b["training_days"][0]["exercises"][0].update(reps_min=None), "required"),
        (
            lambda b: b["training_days"][0]["exercises"][0].update(reps_min=10, reps_max=8),
            "out_of_range",
        ),
        (
            lambda b: b["training_days"][0]["exercises"][0].update(reps_min=8, reps_max=10),
            "invalid_targets",  # linear progression keeps one rep target
        ),
        (lambda b: b["training_days"][0]["exercises"][1].update(target_seconds=None), "required"),
        (lambda b: b["training_days"][0]["exercises"][1].update(reps_min=5), "invalid_targets"),
        (
            lambda b: b["training_days"][0]["exercises"][0].update(target_seconds=30),
            "invalid_targets",
        ),
    ],
)
def test_invalid_training_edits_are_422_and_store_nothing(
    athlete: Api, mutate: Any, code: str
) -> None:
    body = _training_body(_plan(athlete.client))
    mutate(body)
    response = _put(athlete.client, "training", body)
    payload = problem(response, 422, "invalid_plan")
    assert code in {e["code"] for e in payload["errors"]}
    assert _plan(athlete.client)["version"] == 1


def test_unknown_fields_and_out_of_range_values_are_validation_errors(athlete: Api) -> None:
    body = _training_body(_plan(athlete.client))
    body["training_days"][0]["exercises"][0]["sets"] = 11
    problem(_put(athlete.client, "training", body), 422, "validation_error")
    body = _training_body(_plan(athlete.client))
    body["surprise"] = 1
    problem(_put(athlete.client, "training", body), 422, "validation_error")


def test_another_athletes_custom_exercise_cannot_be_planned(athlete: Api) -> None:
    other = athlete.new_client()
    assert other.post("/api/v1/auth/signup", json=_signup("bob@x.test")).status_code == 201
    created = other.post(
        f"{BASE}/exercises",
        json={
            "name": "Bob only",
            "muscle_group": "chest",
            "equipment": "dumbbell",
            "type": "strength",
            "met": 3.5,
            "increment_kg": 2.5,
            "region": "upper",
        },
    )
    assert created.status_code == 201, created.text
    body = _training_body(_plan(athlete.client))
    body["training_days"][0]["exercises"][0]["exercise_id"] = created.json()["id"]
    problem(_put(athlete.client, "training", body), 422, "invalid_plan")


def _signup(email: str, role: str = "athlete") -> dict[str, Any]:
    from tests.integration.auth_helpers import signup_body

    return signup_body(email=email, role=role, display_name=email.split("@")[0].title())


# ───────────── F8.4 authorization ─────────────


def test_f8_4_only_the_owner_may_edit_or_read_versions(athlete: Api) -> None:
    plan = _plan(athlete.client)
    ana = _user_id(athlete)
    stranger = athlete.new_client()
    assert stranger.post("/api/v1/auth/signup", json=_signup("bob@x.test")).status_code == 201
    coach = athlete.new_client()
    assert (
        coach.post("/api/v1/auth/signup", json=_signup("cora@x.test", "coach")).status_code == 201
    )
    anonymous = athlete.new_client()

    for client in (stranger, coach):
        problem(_put(client, "training", _training_body(plan), str(ana)), 403, "not_linked")
        problem(_put(client, "meals", _meals_body(plan), str(ana)), 403, "not_linked")
        problem(client.post(f"{BASE}/athletes/{ana}/plan/regenerate"), 403, "not_linked")
        problem(client.get(f"{BASE}/athletes/{ana}/plan/versions"), 403, "not_linked")
        problem(client.get(f"{BASE}/athletes/{ana}/plan/versions/1"), 403, "not_linked")
    problem(_put(anonymous, "training", _training_body(plan), str(ana)), 401, "not_authenticated")
    # A coach has no plan of their own either.
    problem(_put(coach, "training", _training_body(plan)), 403, "not_linked")
    with Session(athlete.app.state.engine) as session:
        assert session.scalar(select(func.count()).select_from(Plan)) == 1
    # The owner may, by "me" and by id.
    assert _put(athlete.client, "training", _training_body(plan), str(ana)).status_code == 200


# ───────────── meals: D73 and F8 ─────────────


def _log(client: TestClient, planned_meal_id: str, status: str = "eaten") -> dict[str, Any]:
    response = client.post(
        f"{ME}/meal-logs", json={"date": THU, "planned_meal_id": planned_meal_id, "status": status}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_reordering_replacing_and_regramming_the_same_day_keeps_the_log(athlete: Api) -> None:
    day = _day(athlete.client)
    logged_meal = day["meals"][1]["planned_meal"]  # lunch
    log = _log(athlete.client, logged_meal["id"])["meal_log"]
    eaten_before = _day(athlete.client)["energy"]["eaten"]

    def check(label: str) -> dict[str, Any]:
        after = _day(athlete.client)
        row = next(m for m in after["meals"] if m["log"] is not None)
        assert row["log"]["id"] == log["id"], label
        assert row["log"]["planned_meal_id"] == row["planned_meal"]["id"], label
        assert after["extra_meal_logs"] == [], label
        assert after["energy"]["eaten"] == eaten_before, label
        return after

    # 1. reorder: lunch first.
    plan = _plan(athlete.client)
    body = _meals_body(plan)
    for d in body["meal_days"]:
        d["meals"] = list(reversed(d["meals"]))
    response = _put(athlete.client, "meals", body)
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "custom" and response.json()["version"] == 2
    after = check("reorder")
    assert after["meals"][1]["log"] is not None  # middle of three, whichever order

    # 2. replace the logged meal in place (same id, another library meal).
    plan = _plan(athlete.client)
    other = next(m for m in _library_meals(athlete) if m not in _meal_ids(plan))
    body = _meals_body(plan)
    target = next(m for m in _thursday(body)["meals"] if m["id"] == _logged_id(athlete))
    target["meal_id"] = other
    assert _put(athlete.client, "meals", body).status_code == 200
    check("replace")

    # 3. change the grams: a private copy owned by the athlete, the library meal is untouched.
    plan = _plan(athlete.client)
    body = _meals_body(plan)
    target = next(m for m in _thursday(body)["meals"] if m["id"] == _logged_id(athlete))
    meal_id = target["meal_id"]
    with Session(athlete.app.state.engine) as session:
        library_before = _meal_items(session, meal_id)
        food_id = str(library_before[0][0])
    target["items"] = [{"food_id": food_id, "grams": 123.4}]
    response = _put(athlete.client, "meals", body)
    assert response.status_code == 200, response.text
    after = check("grams")
    planned = next(m for m in after["meals"] if m["log"] is not None)["planned_meal"]
    assert [i["grams"] for i in planned["items"]] == [123.4] and planned["portion_factor"] == 1
    with Session(athlete.app.state.engine) as session:
        assert _meal_items(session, meal_id) == library_before
        copy_ = session.get(Meal, uuid.UUID(planned["meal"]["id"]))
        assert copy_ is not None and copy_.owner_id == _user_id(athlete) and copy_.id != meal_id


def test_removing_a_logged_meal_moves_its_log_to_extras_and_a_new_meal_has_none(
    athlete: Api,
) -> None:
    day = _day(athlete.client)
    logged = day["meals"][0]["planned_meal"]
    _log(athlete.client, logged["id"])
    plan = _plan(athlete.client)
    body = _meals_body(plan)
    thursday = next(d for d in body["meal_days"] if d["weekday"] == "thu")
    removed = thursday["meals"].pop(0)
    added = copy.deepcopy(removed)
    added.pop("id")  # same meal, but added by hand: a new meal, no log
    thursday["meals"].append(added)
    assert _put(athlete.client, "meals", body).status_code == 200
    after = _day(athlete.client)
    assert all(m["log"] is None for m in after["meals"])
    assert len(after["extra_meal_logs"]) == 1
    assert after["energy"]["eaten"]["kcal"] == logged["totals"]["kcal"]  # still counted, visible


def test_the_past_keeps_its_meals_after_a_meal_edit(athlete: Api) -> None:
    before = [m["planned_meal"]["meal"]["id"] for m in _day(athlete.client, LAST_THU)["meals"]]
    body = _meals_body(_plan(athlete.client))
    for d in body["meal_days"]:
        d["meals"] = d["meals"][:1]
    assert _put(athlete.client, "meals", body).status_code == 200
    assert [m["planned_meal"]["meal"]["id"] for m in _day(athlete.client, LAST_THU)["meals"]] == (
        before
    )
    assert len(_day(athlete.client, THU)["meals"]) == 1


def test_meal_edit_validation_and_a_day_with_no_meals(athlete: Api) -> None:
    plan = _plan(athlete.client)
    body = _meals_body(plan)
    body["meal_days"][1]["weekday"] = body["meal_days"][0]["weekday"]
    problem(_put(athlete.client, "meals", body), 422, "invalid_plan")
    body = _meals_body(plan)
    body["meal_days"][0]["meals"][0]["id"] = str(uuid.uuid4())
    problem(_put(athlete.client, "meals", body), 422, "invalid_plan")
    body = _meals_body(plan)
    body["meal_days"][0]["meals"][0]["meal_id"] = str(uuid.uuid4())
    problem(_put(athlete.client, "meals", body), 422, "invalid_plan")
    body = _meals_body(plan)
    body["meal_days"][0]["meals"][0]["items"] = [{"food_id": str(uuid.uuid4()), "grams": 10}]
    problem(_put(athlete.client, "meals", body), 422, "invalid_plan")
    body = _meals_body(plan)
    first = body["meal_days"][0]["meals"][0]
    body["meal_days"][0]["meals"].append(copy.deepcopy(first))  # same planned id twice
    problem(_put(athlete.client, "meals", body), 422, "invalid_plan")
    body = _meals_body(plan)
    body["meal_days"][0]["meals"] = []
    ok = _put(athlete.client, "meals", body)
    assert ok.status_code == 200 and ok.json()["meal_days"][0]["meals"] == []
    assert _plan(athlete.client)["version"] == 2


def test_a_training_edit_carries_the_meal_keys_so_logs_survive(athlete: Api) -> None:
    logged = _day(athlete.client)["meals"][0]["planned_meal"]
    log = _log(athlete.client, logged["id"])["meal_log"]
    body = _training_body(_plan(athlete.client))
    body["training_days"][0]["name"] = "Renamed"
    assert _put(athlete.client, "training", body).status_code == 200
    row = _day(athlete.client)["meals"][0]
    assert row["log"]["id"] == log["id"]


# ───────────── helpers for the meal tests ─────────────


def _library_meals(api: Api) -> list[str]:
    with Session(api.app.state.engine) as session:
        return [
            str(i)
            for i in session.scalars(
                select(Meal.id).where(Meal.owner_id.is_(None)).order_by(Meal.name)
            )
        ]


def _meal_ids(plan: dict[str, Any]) -> set[str]:
    return {m["meal"]["id"] for d in plan["meal_days"] for m in d["meals"]}


def _logged_id(api: Api) -> str:
    """The current planned meal id of the meal that shows a log today."""
    row = next(m for m in _day(api.client)["meals"] if m["log"] is not None)
    return str(row["planned_meal"]["id"])


def _thursday(body: dict[str, Any]) -> dict[str, Any]:
    return next(d for d in body["meal_days"] if d["weekday"] == "thu")


def _meal_items(session: Session, meal_id: str) -> list[tuple[uuid.UUID, float]]:
    return [
        (i.food_id, float(i.grams))
        for i in session.scalars(
            select(MealItem)
            .where(MealItem.meal_id == uuid.UUID(meal_id))
            .order_by(MealItem.position)
        )
    ]
