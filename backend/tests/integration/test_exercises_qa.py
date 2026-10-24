"""QA (#22): extra checks on the F4 exercise catalog that the PR's own tests do not cover:
telemetry privacy, edge inputs (D40), forged cursors (F4.3), name normalisation for the 409 rule,
seed robustness and the migration round trip."""

import base64
import json
import os
import subprocess
import sys
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.main import create_app
from app.migrations import BACKEND_DIR
from app.models import Exercise
from app.seed import run_seed
from app.seed_exercises import _NAMESPACE, SEED_EXERCISES, load_exercises
from tests.conftest import Captured, JsonLogs, captured_telemetry, make_settings
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem, signup_body

URL = "/api/v1/exercises"
# Pinned: later migrations (e.g. plan tables) depend on `exercise`, so "head" is not this one.
EXERCISE_REVISION = "a7d3e5f10b64"
PREVIOUS_REVISION = "9c4f2a7e1b30"  # head before #22


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


def _cursor(name: Any, exercise_id: Any) -> str:
    raw = json.dumps([name, exercise_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture
def seeded(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
        session.commit()
    assert api.signup().status_code == 201
    return api


def _sign_up(api: Api, email: str, role: str = "athlete") -> TestClient:
    client = api.new_client()
    body = signup_body(email=email, role=role, display_name="Other")
    assert client.post("/api/v1/auth/signup", json=body).status_code == 201
    return client


# ───────────── telemetry privacy (CLAUDE.md rule 6, spec §6.5) ─────────────


def test_exercise_names_and_search_terms_never_reach_logs_or_spans(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    captured = Captured(app, telemetry, span_exporter, metric_reader)
    secret = "Zqxsecretdrill"
    with Session(app.state.engine) as session:
        run_seed(session)
        session.commit()
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/signup", json=signup_body()).status_code == 201
        assert client.post(URL, json=_body(name=secret)).status_code == 201
        assert client.post(URL, json=_body(name=secret.upper())).status_code == 409
        assert client.post(URL, json=_body(name=secret, met=99)).status_code == 422
        assert client.get(URL, params={"q": secret.lower()}).status_code == 200
        page = client.get(URL, params={"limit": 1}).json()
        assert client.get(URL, params={"cursor": page["next_cursor"]}).status_code == 200
        assert client.get(URL, params={"q": secret, "muscle_group": "wings"}).status_code == 400

    texts = [json_logs.text] + [span.to_json() for span in captured.spans()]
    for blob in texts:
        assert secret.lower() not in blob.lower()
        assert "ana@x.test" not in blob
        assert page["next_cursor"] not in blob
        assert page["items"][0]["name"] not in blob


# ───────────── edge inputs (D40: invalid query parameter -> 400, bad body -> 422) ─────────────


def test_a_search_term_longer_than_100_chars_is_400(seeded: Api) -> None:
    problem(seeded.client.get(URL, params={"q": "a" * 101}), 400, "bad_request")
    assert seeded.client.get(URL, params={"q": "a" * 100}).status_code == 200


@pytest.mark.parametrize(
    "cursor",
    [
        _cursor(1, str(uuid.uuid4())),  # name is not a string
        _cursor("a", "not-a-uuid"),
        base64.urlsafe_b64encode(b'{"a": 1}').decode(),
        base64.urlsafe_b64encode(b"null").decode(),
        base64.urlsafe_b64encode(b'["a", "b", "c"]').decode(),
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
        "!!!",
    ],
)
def test_forged_or_garbled_cursors_are_400(seeded: Api, cursor: str) -> None:
    problem(seeded.client.get(URL, params={"cursor": cursor}), 400, "bad_request")


# Known defect #102: a NUL reaches Postgres and becomes a 500. Remove the marks when fixed.
NUL_DEFECT = pytest.mark.xfail(strict=True, reason="#102: NUL byte gives 500 (DataError)")


@NUL_DEFECT
def test_a_nul_byte_in_the_search_term_is_not_a_server_error(seeded: Api) -> None:
    response = seeded.client.get(URL, params={"q": "push\x00"})
    assert response.status_code in (200, 400), response.text


@NUL_DEFECT
def test_a_nul_byte_in_a_cursor_is_400_not_a_server_error(seeded: Api) -> None:
    cursor = _cursor("push\x00", str(uuid.uuid4()))
    problem(seeded.client.get(URL, params={"cursor": cursor}), 400, "bad_request")


@NUL_DEFECT
def test_a_nul_byte_in_a_custom_name_is_not_a_server_error(seeded: Api) -> None:
    response = seeded.client.post(URL, json=_body(name="Sled\x00push"))
    assert response.status_code in (201, 422), response.text


# ───────────── F4.3: a forged cursor never reveals another user's exercise ─────────────


def test_a_forged_cursor_does_not_reveal_a_strangers_custom_exercise(seeded: Api) -> None:
    created = seeded.client.post(URL, json=_body(name="Aaa hidden drill")).json()
    stranger = _sign_up(seeded, "bo@x.test")
    coach = _sign_up(seeded, "coach@x.test", role="coach")
    before = _cursor("aaa", "00000000-0000-0000-0000-000000000000")
    for client in (stranger, coach):
        page = client.get(URL, params={"cursor": before, "limit": 100}).json()
        assert created["id"] not in {item["id"] for item in page["items"]}
        assert all(item["is_custom"] is False for item in page["items"])


# ───────────── 409 rule: names are compared after trimming, case-insensitively ─────────────


def test_a_padded_differently_cased_seed_name_is_409(seeded: Api) -> None:
    problem(seeded.client.post(URL, json=_body(name="  PUSH-UP  ")), 409, "exercise_name_taken")


def test_a_custom_name_is_stored_trimmed(seeded: Api) -> None:
    created = seeded.client.post(URL, json=_body(name="  Sled push  "))
    assert created.status_code == 201
    assert created.json()["name"] == "Sled push"
    problem(seeded.client.post(URL, json=_body(name="sled push")), 409, "exercise_name_taken")


def test_a_strangers_custom_name_does_not_block_a_new_name(seeded: Api) -> None:
    stranger = _sign_up(seeded, "bo@x.test")
    assert stranger.post(URL, json=_body(name="Shared name")).status_code == 201
    assert seeded.client.post(URL, json=_body(name="SHARED NAME")).status_code == 201


def test_a_non_ascii_name_is_409_case_insensitively(seeded: Api) -> None:
    assert seeded.client.post(URL, json=_body(name="Press francés")).status_code == 201
    problem(seeded.client.post(URL, json=_body(name="PRESS FRANCÉS")), 409, "exercise_name_taken")
    names = [e["name"] for e in seeded.client.get(URL, params={"q": "FRANCÉS"}).json()["items"]]
    assert names == ["Press francés"]


# ───────────── seed: values are the seed data; edited rows are kept ─────────────


def test_seeded_rows_carry_the_seed_values_and_stable_ids(seeded: Api) -> None:
    by_name = {e.name: e for e in SEED_EXERCISES}
    seen: dict[str, dict[str, Any]] = {}
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        page = seeded.client.get(URL, params=params).json()
        seen.update({item["name"]: item for item in page["items"]})
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert set(seen) == set(by_name)
    for name, item in seen.items():
        seed = by_name[name]
        assert (
            item["muscle_group"],
            item["equipment"],
            item["type"],
            item["met"],
            item["increment_kg"],
            item["region"],
            item["allows_added_weight"],
        ) == (
            seed.muscle_group,
            seed.equipment,
            seed.type,
            seed.met,
            seed.increment_kg,
            seed.region,
            seed.allows_added_weight,
        )
        assert item["id"] == str(
            uuid.uuid5(uuid.UUID("5e1f7c0e-3a52-4c1b-9d58-0f1d2a6b7c40"), name.lower())
        )


def test_an_edited_seed_row_keeps_every_edited_field(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        run_seed(session)
        session.commit()
        session.execute(
            text(
                "UPDATE exercise SET met = 9, increment_kg = 5, allows_added_weight = false,"
                " equipment = 'band' WHERE name = 'Pull-up'"
            )
        )
        session.commit()
        assert run_seed(session) == 0
        session.commit()
        row = session.execute(
            text(
                "SELECT met, increment_kg, allows_added_weight, equipment FROM exercise"
                " WHERE name = 'Pull-up'"
            )
        ).one()
    assert tuple(row) == (9, 5, False, "band")


def test_the_seed_step_still_succeeds_after_a_seed_row_is_renamed(api: Api) -> None:
    """A seed row renamed by an operator must not make the next migration step fail."""
    with Session(api.app.state.engine) as session:
        run_seed(session)
        session.commit()
        session.execute(
            text("UPDATE exercise SET name = 'Push-up (strict)' WHERE name = 'Push-up'")
        )
        session.commit()
    with Session(api.app.state.engine) as session:
        assert load_exercises(session) == 0  # must not raise
        session.commit()
        rows = session.execute(
            text("SELECT name FROM exercise WHERE id = :id"), {"id": _push_up_id()}
        ).all()
        assert [r[0] for r in rows] == ["Push-up (strict)"]
        assert (
            session.execute(text("SELECT 1 FROM exercise WHERE name = 'Push-up'")).first() is None
        )
        assert session.scalar(text("SELECT count(*) FROM exercise")) == len(SEED_EXERCISES)


def _push_up_id() -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, "push-up")


def test_a_seed_row_with_the_same_name_but_another_id_is_skipped(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        session.add(
            Exercise(
                id=uuid.uuid4(),
                owner_id=None,
                name="PUSH-UP",
                muscle_group="chest",
                equipment="bodyweight",
                type="bodyweight",
                met=3.8,
                increment_kg=0,
                region="upper",
            )
        )
        session.commit()
        assert load_exercises(session) == len(SEED_EXERCISES) - 1
        session.commit()
        assert (
            session.scalar(text("SELECT count(*) FROM exercise WHERE lower(name)='push-up'")) == 1
        )


def test_a_second_run_on_a_fresh_database_inserts_nothing(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        assert load_exercises(session) == len(SEED_EXERCISES)
        session.commit()
        assert load_exercises(session) == 0
        session.commit()
        assert session.scalar(text("SELECT count(*) FROM exercise")) == len(SEED_EXERCISES)


def test_a_seed_entry_renamed_in_code_leaves_the_old_row_and_does_not_fail(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documented behaviour: no automatic rename migration; the old row stays."""
    with Session(api.app.state.engine) as session:
        load_exercises(session)
        session.commit()
    renamed = tuple(
        e._replace(name="Press-up") if e.name == "Push-up" else e for e in SEED_EXERCISES
    )
    monkeypatch.setattr("app.seed_exercises.SEED_EXERCISES", renamed)
    with Session(api.app.state.engine) as session:
        assert load_exercises(session) == 1
        session.commit()
        names = set(session.scalars(text("SELECT name FROM exercise")))
    assert {"Push-up", "Press-up"} <= names


# ───────────── migration: expand-only round trip ─────────────


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_the_exercise_migration_downgrades_and_upgrades_without_touching_users(
    fresh_database_url: str,
) -> None:
    assert _alembic(fresh_database_url, "upgrade", PREVIOUS_REVISION).returncode == 0
    engine = create_engine(fresh_database_url)
    before = {
        table: {c["name"] for c in inspect(engine).get_columns(table)}
        for table in inspect(engine).get_table_names()
    }
    engine.dispose()

    up = _alembic(fresh_database_url, "upgrade", EXERCISE_REVISION)
    assert up.returncode == 0, up.stderr
    engine = create_engine(fresh_database_url)
    after = {
        table: {c["name"] for c in inspect(engine).get_columns(table)}
        for table in inspect(engine).get_table_names()
    }
    engine.dispose()
    # Expand-only: one new table, every existing table and column unchanged.
    assert set(after) - set(before) == {"exercise"}
    assert {t: after[t] for t in before} == before

    down = _alembic(fresh_database_url, "downgrade", PREVIOUS_REVISION)
    assert down.returncode == 0, down.stderr
    engine = create_engine(fresh_database_url)
    assert "exercise" not in inspect(engine).get_table_names()
    engine.dispose()
    again = _alembic(fresh_database_url, "upgrade", EXERCISE_REVISION)
    assert again.returncode == 0, again.stderr


def test_swapped_seed_row_names_cause_no_unique_or_pk_violation(api: Api) -> None:
    """QA #103: Push-up renamed to Pull-up's old name, Pull-up renamed away: 0 inserts."""
    with Session(api.app.state.engine) as session:
        load_exercises(session)
        session.execute(text("UPDATE exercise SET name = 'Pull-up (old)' WHERE name = 'Pull-up'"))
        session.execute(text("UPDATE exercise SET name = 'Pull-up' WHERE name = 'Push-up'"))
        session.commit()
        assert load_exercises(session) == 0
        session.commit()
        assert session.scalar(text("SELECT count(*) FROM exercise")) == len(SEED_EXERCISES)
