"""F4 exercise catalog against real Postgres: seed, search, filters, pagination, custom exercises,
visibility (F4.3) and contract conformance."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.models import Exercise
from app.models.exercise import EQUIPMENT, MUSCLE_GROUPS
from app.seed import run_seed
from app.seed_exercises import SEED_EXERCISES, load_exercises
from tests.contract import assert_matches_schema, schema_validator
from tests.integration.auth_helpers import Api, field_errors, problem

URL = "/api/v1/exercises"


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Sled push",
        "muscle_group": "quads",
        "equipment": "none",
        "type": "strength",
        "met": 6.5,
        "region": "lower",
    }
    body.update(overrides)
    return body


@pytest.fixture
def seeded(api: Api) -> Api:
    """An API whose database has the seed catalog, with an athlete signed in."""
    engine = api.app.state.engine
    with Session(engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    return api


def _all(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = {**params, "limit": 100, **({"cursor": cursor} if cursor else {})}
        page = client.get(URL, params=query).json()
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items


# ───────────── seed content (F4, F4.1) ─────────────


def test_seed_has_60_to_80_unique_valid_exercises() -> None:
    assert 60 <= len(SEED_EXERCISES) <= 80
    assert len({e.name.lower() for e in SEED_EXERCISES}) == len(SEED_EXERCISES)
    for e in SEED_EXERCISES:
        assert len(e.name) >= 2
        assert e.muscle_group in MUSCLE_GROUPS
        assert e.equipment in EQUIPMENT
        assert 1 <= e.met <= 20
        assert 0 <= e.increment_kg <= 20


# F5 equipment variants (spec F5): which exercise equipment each one can use.
VARIANTS = {
    "full_gym": set(EQUIPMENT),
    "home_dumbbells": {"dumbbell", "bodyweight", "band", "none"},
    "bodyweight_only": {"bodyweight", "none"},
}


@pytest.mark.parametrize("variant", VARIANTS)
def test_seed_covers_every_f5_equipment_variant(variant: str) -> None:
    usable = [e for e in SEED_EXERCISES if e.equipment in VARIANTS[variant]]
    for group in ("chest", "back", "shoulders", "quads", "hamstrings", "glutes", "core"):
        assert any(
            e.muscle_group == group and e.type in ("strength", "bodyweight") for e in usable
        ), f"{variant} has no strength/bodyweight {group} exercise"
    assert any(e.muscle_group == "cardio" and e.type == "timed" for e in usable), variant


def test_seed_marks_loadable_bodyweight_exercises() -> None:
    flagged = {e.name for e in SEED_EXERCISES if e.allows_added_weight}
    assert {"Pull-up", "Chin-up", "Bench dip", "Push-up"} <= flagged
    assert all(e.type == "bodyweight" for e in SEED_EXERCISES if e.allows_added_weight)


def test_seed_runs_twice_without_changing_rows(api: Api) -> None:
    engine = api.app.state.engine

    def snapshot() -> list[tuple[Any, ...]]:
        with Session(engine) as session:
            rows = session.execute(select(Exercise).order_by(Exercise.id)).scalars()
            return [
                (
                    *(e.id, e.owner_id, e.name, e.muscle_group, e.equipment, e.type),
                    *(float(e.met), float(e.increment_kg), e.region, e.allows_added_weight),
                )
                for e in rows
            ]

    with Session(engine) as session:
        assert run_seed(session) == len(SEED_EXERCISES)
    first = snapshot()
    with Session(engine) as session:
        assert run_seed(session) == 0
        assert load_exercises(session) == 0
    assert snapshot() == first
    assert len(first) == len(SEED_EXERCISES)
    assert all(row[1] is None for row in first)


def test_seed_does_not_overwrite_an_edited_seed_row(api: Api) -> None:
    engine = api.app.state.engine
    with Session(engine) as session:
        run_seed(session)
        session.execute(text("UPDATE exercise SET met = 7 WHERE name = 'Push-up'"))
        session.commit()
        run_seed(session)
        assert session.scalar(select(Exercise.met).where(Exercise.name == "Push-up")) == 7


# ───────────── GET /exercises ─────────────


def test_list_requires_a_session(seeded: Api) -> None:
    problem(seeded.new_client().get(URL), 401, "not_authenticated")
    problem(seeded.new_client().post(URL, json=_body()), 401, "not_authenticated")


def test_list_returns_seed_exercises_ordered_by_name_and_matches_the_contract(
    seeded: Api,
) -> None:
    response = seeded.client.get(URL)
    assert response.status_code == 200
    page = response.json()
    assert_matches_schema(page, "ExercisePage")
    names = [item["name"] for item in page["items"]]
    assert len(names) == 50  # default limit
    with seeded.app.state.engine.connect() as connection:
        expected = (
            connection.execute(text("SELECT name FROM exercise ORDER BY lower(name), id LIMIT 50"))
            .scalars()
            .all()
        )
    assert names == expected
    assert page["next_cursor"] is not None
    assert all(item["is_custom"] is False and item["owner"] is None for item in page["items"])


def test_pagination_walks_the_whole_catalog_without_gaps_or_repeats(seeded: Api) -> None:
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 7}
        if cursor:
            params["cursor"] = cursor
        page = seeded.client.get(URL, params=params).json()
        assert len(page["items"]) <= 7
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == len(SEED_EXERCISES)


def test_search_is_case_insensitive_on_name(seeded: Api) -> None:
    lower = [e["name"] for e in _all(seeded.client, q="push")]
    upper = [e["name"] for e in _all(seeded.client, q="PUSH")]
    assert lower == upper
    assert "Push-up" in lower
    assert all("push" in name.lower() for name in lower)
    assert _all(seeded.client, q="zzzz-no-match") == []


def test_search_treats_like_wildcards_literally(seeded: Api) -> None:
    assert _all(seeded.client, q="%") == []
    assert _all(seeded.client, q="_") == []


def test_filters_work_alone_and_combine_with_and(seeded: Api) -> None:
    chest = _all(seeded.client, muscle_group="chest")
    assert chest
    assert {e["muscle_group"] for e in chest} == {"chest"}

    combined = _all(
        seeded.client, muscle_group="chest", equipment="bodyweight", type="bodyweight", q="push"
    )
    assert {e["name"] for e in combined} == {"Push-up", "Incline push-up"}
    assert _all(seeded.client, muscle_group="chest", equipment="cardio_machine") == []

    assert {e["region"] for e in _all(seeded.client, region="cardio")} == {"cardio"}
    assert {e["type"] for e in _all(seeded.client, type="timed")} == {"timed"}
    assert {e["equipment"] for e in _all(seeded.client, equipment="band")} == {"band"}


@pytest.mark.parametrize(
    "params",
    [
        {"muscle_group": "wings"},
        {"equipment": "rocket"},
        {"type": "magic"},
        {"region": "moon"},
        {"limit": 0},
        {"limit": 101},
        {"cursor": "not-a-cursor"},
        {"cursor": "e1wiYSI6MX0"},
    ],
)
def test_invalid_query_values_are_400(seeded: Api, params: dict[str, Any]) -> None:
    problem(seeded.client.get(URL, params=params), 400, "bad_request")


# ───────────── POST /exercises ─────────────


def test_create_custom_exercise_returns_201_owned_by_the_caller(seeded: Api) -> None:
    response = seeded.client.post(URL, json=_body())

    assert response.status_code == 201
    created = response.json()
    assert_matches_schema(created, "Exercise")
    assert created["is_custom"] is True
    assert created["increment_kg"] == 2.5
    assert created["allows_added_weight"] is False
    me = seeded.client.get("/api/v1/me").json()
    assert created["owner"] == {"id": me["id"], "display_name": "Ana", "role": "athlete"}
    assert created["id"] in {e["id"] for e in _all(seeded.client, q="sled")}


def test_create_accepts_allows_added_weight_and_a_coach_can_create(seeded: Api) -> None:
    response = seeded.client.post(
        URL, json=_body(name="Ring dip", equipment="bodyweight", allows_added_weight=True)
    )
    assert response.status_code == 201
    assert response.json()["allows_added_weight"] is True

    coach = seeded.new_client()
    body = {
        "email": "coach@x.test",
        "password": "correct-horse-battery",
        "display_name": "Coach",
        "role": "coach",
        "birth_date": "1985-01-01",
        "units": "metric",
        "timezone": "Europe/Madrid",
        "accept_disclaimer": True,
    }
    assert coach.post("/api/v1/auth/signup", json=body).status_code == 201
    created = coach.post(URL, json=_body(name="Coach drill"))
    assert created.status_code == 201
    assert created.json()["owner"]["role"] == "coach"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"met": 0.5}, "met"),
        ({"met": 20.5}, "met"),
        ({"name": "x"}, "name"),
        ({"name": "x" * 81}, "name"),
        ({"muscle_group": "wings"}, "muscle_group"),
        ({"increment_kg": -1}, "increment_kg"),
        ({"increment_kg": 21}, "increment_kg"),
        ({"region": "moon"}, "region"),
        ({"unknown": 1}, "unknown"),
    ],
)
def test_schema_violations_are_422(seeded: Api, overrides: dict[str, Any], field: str) -> None:
    body = problem(seeded.client.post(URL, json=_body(**overrides)), 422, "validation_error")
    assert any(f == field for f, _ in field_errors(body))


def test_missing_required_fields_are_422(seeded: Api) -> None:
    problem(seeded.client.post(URL, json={"name": "Only a name"}), 422, "validation_error")


def test_a_duplicate_name_is_409_case_insensitively(seeded: Api) -> None:
    assert seeded.client.post(URL, json=_body()).status_code == 201
    problem(seeded.client.post(URL, json=_body(name="SLED PUSH")), 409, "exercise_name_taken")
    problem(seeded.client.post(URL, json=_body(name="push-up")), 409, "exercise_name_taken")


def test_two_users_may_use_the_same_custom_name(seeded: Api) -> None:
    other = seeded.new_client()
    other_body = {
        "email": "bo@x.test",
        "password": "correct-horse-battery",
        "display_name": "Bo",
        "role": "athlete",
        "birth_date": "1990-01-01",
        "units": "metric",
        "timezone": "Europe/Madrid",
        "accept_disclaimer": True,
    }
    assert other.post("/api/v1/auth/signup", json=other_body).status_code == 201
    assert seeded.client.post(URL, json=_body()).status_code == 201
    assert other.post(URL, json=_body()).status_code == 201


# ───────────── F4.3 visibility ─────────────


def _sign_up(api: Api, email: str, role: str, name: str) -> TestClient:
    client = api.new_client()
    body = {
        "email": email,
        "password": "correct-horse-battery",
        "display_name": name,
        "role": role,
        "birth_date": "1990-01-01",
        "units": "metric",
        "timezone": "Europe/Madrid",
        "accept_disclaimer": True,
    }
    assert client.post("/api/v1/auth/signup", json=body).status_code == 201
    return client


def test_a_custom_exercise_is_visible_to_its_creator_and_never_to_strangers(seeded: Api) -> None:
    creator = seeded.client
    athlete = _sign_up(seeded, "bo@x.test", "athlete", "Bo")
    coach = _sign_up(seeded, "coach@x.test", "coach", "Coach")
    created = creator.post(URL, json=_body(name="Secret sled drill")).json()

    assert created["id"] in {e["id"] for e in _all(creator, q="secret")}
    for stranger in (athlete, coach):
        assert _all(stranger, q="secret") == []
        assert created["id"] not in {e["id"] for e in _all(stranger)}
        assert created["id"] not in {e["id"] for e in _all(stranger, muscle_group="quads")}
    # A stranger's own exercise with the same name does not collide or leak.
    mine = coach.post(URL, json=_body(name="Secret sled drill"))
    assert mine.status_code == 201
    assert [e["id"] for e in _all(coach, q="secret")] == [mine.json()["id"]]
    assert [e["id"] for e in _all(creator, q="secret")] == [created["id"]]


def test_exercise_input_schema_rejects_unknown_properties() -> None:
    validator = schema_validator("ExerciseInput")
    assert not list(validator.iter_errors(_body()))
    assert list(validator.iter_errors(_body(unknown=1)))


# ───────────── migration ─────────────


def test_allows_added_weight_defaults_to_false_for_rows_without_it(api: Api) -> None:
    engine = create_engine(api.app.state.engine.url.render_as_string(hide_password=False))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO exercise (id, name, muscle_group, equipment, type, met, increment_kg,"
                " region) VALUES (gen_random_uuid(), 'Legacy', 'chest', 'none', 'strength', 3, 0,"
                " 'upper')"
            )
        )
        value = connection.scalar(
            text("SELECT allows_added_weight FROM exercise WHERE name = 'Legacy'")
        )
        count = connection.scalar(select(func.count()).select_from(text("exercise")))
    engine.dispose()
    assert value is False
    assert count == 1
