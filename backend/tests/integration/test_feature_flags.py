"""Feature flags against real Postgres (issue #15): migration, reader, ops CLI, audit, latency.

The CLI is run as a subprocess (`python -m app.cli.flags`), the way `oncall/ops/flag.sh` runs it
inside the backend container, and the running app is a `create_app` instance whose flag cache is
driven by a `FakeClock`, so "seen within the TTL without a restart" is tested deterministically.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text

from app.config import FLAG_CACHE_TTL_SECONDS
from app.db import make_session_factory
from app.migrations import BACKEND_DIR
from app.services.flags import DEFAULT_FLAGS, FlagReader, set_flag
from tests.conftest import JsonLogs
from tests.integration.auth_helpers import NOW, Api
from tests.integration.conftest import alembic_config

FLAG_REVISION = "9c4f2a7e1b30"
PREVIOUS_REVISION = "5b8e1d0c7a42"


# ------------------------------------------------------------------------------------------
# helpers


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    yield engine
    engine.dispose()


def rows(engine: Engine) -> dict[str, dict[str, Any]]:
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT key, value, updated_by, updated_at FROM feature_flag")
        ).mappings()
        return {row["key"]: dict(row) for row in result}


def insert_raw(engine: Engine, key: str, value: str) -> None:
    """A stored value written by hand (or by a newer release), bypassing validation."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO feature_flag (key, value, updated_by, updated_at) "
                "VALUES (:key, :value, 'owner', now())"
            ),
            {"key": key, "value": value},
        )


def run_cli(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_", "APP_"))},
        "DATABASE_URL": database_url,
        "APP_ENV": "test",
    }
    return subprocess.run(
        [sys.executable, "-m", "app.cli.flags", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


# ------------------------------------------------------------------------------------------
# AC1 migration


def test_migration_creates_feature_flag_with_the_spec_columns(db: Engine) -> None:
    inspector = inspect(db)
    columns = {column["name"]: column for column in inspector.get_columns("feature_flag")}
    assert set(columns) == {"key", "value", "updated_by", "updated_at"}
    assert inspector.get_pk_constraint("feature_flag")["constrained_columns"] == ["key"]
    assert all(not column["nullable"] for column in columns.values())
    assert getattr(columns["updated_at"]["type"], "timezone", None) is True  # timestamptz


def test_migration_is_expand_only_and_seeds_nothing(fresh_database_url: str) -> None:
    """From the previous head, the revision only adds `feature_flag`; nothing existing changes,
    so the previous release runs unchanged on the new schema (and a rollback is possible)."""
    config = alembic_config(fresh_database_url)
    engine = create_engine(fresh_database_url)

    def schema() -> dict[str, list[tuple[str, str, bool]]]:
        inspector = inspect(engine)
        return {
            table: [
                (c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)
            ]
            for table in inspector.get_table_names()
            if table != "alembic_version"
        }

    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = schema()
        command.upgrade(config, FLAG_REVISION)
        after = schema()
        assert set(after) - set(before) == {"feature_flag"}
        assert {t: c for t, c in after.items() if t != "feature_flag"} == before
        assert rows(engine) == {}  # no seeded rows: a missing row means the config default

        command.downgrade(config, PREVIOUS_REVISION)
        assert schema() == before
        command.upgrade(config, "head")
    finally:
        engine.dispose()


# ------------------------------------------------------------------------------------------
# AC3 reader defaults and fallbacks


def test_reader_returns_defaults_when_no_row_exists(api: Api) -> None:
    assert api.app.state.flags.values() == DEFAULT_FLAGS


@pytest.mark.parametrize("stored", ["v9", "V2", "", "legacy"])
def test_reader_returns_v1_for_an_unknown_progression_engine(
    api: Api, migrated_database_url: str, stored: str, json_logs: JsonLogs
) -> None:
    engine = create_engine(migrated_database_url)
    insert_raw(engine, "progression_engine", stored)
    engine.dispose()

    assert api.app.state.flags.values().progression_engine == "v1"
    [line] = json_logs.with_message("feature flag invalid stored value")
    assert line["flag_key"] == "progression_engine"
    assert stored == "" or stored not in json_logs.text  # the stored text is never logged


def test_reader_reads_valid_stored_values(api: Api, migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    insert_raw(engine, "progression_engine", "v2")
    insert_raw(engine, "off_search_enabled", "false")
    insert_raw(engine, "fault_injection_latency_ms", "250")
    insert_raw(engine, "meal_planner", "true")  # not allow-listed: ignored
    engine.dispose()

    values = api.app.state.flags.values()
    assert (values.progression_engine, values.off_search_enabled) == ("v2", False)
    assert values.fault_injection_latency_ms == 250


# ------------------------------------------------------------------------------------------
# AC4 a CLI change is seen by a running backend within the TTL (< 10 s), without a restart


def test_cli_change_is_seen_by_the_running_app_within_the_ttl(
    api: Api, migrated_database_url: str
) -> None:
    reader: FlagReader = api.app.state.flags
    assert reader.values().progression_engine == "v1"  # cached now

    result = run_cli(migrated_database_url, "set", "progression_engine", "v2", "--actor", "owner")
    assert result.returncode == 0, result.stderr

    api.clock.advance(seconds=FLAG_CACHE_TTL_SECONDS - 0.5)
    assert reader.values().progression_engine == "v1"  # still inside the TTL
    api.clock.advance(seconds=0.5)
    assert reader.values().progression_engine == "v2"  # same process, no restart
    assert FLAG_CACHE_TTL_SECONDS < 10


def test_real_time_ttl_with_the_system_clock(migrated_database_url: str) -> None:
    """Same property with wall-clock time and a short TTL (no FakeClock involved)."""
    engine = create_engine(migrated_database_url)
    reader = FlagReader(
        make_session_factory(engine), now=lambda: dt.datetime.now(dt.UTC), ttl_seconds=0.3
    )
    try:
        assert reader.values().off_search_enabled is True
        result = run_cli(
            migrated_database_url, "set", "off_search_enabled", "false", "--actor", "owner"
        )
        assert result.returncode == 0, result.stderr
        time.sleep(0.35)
        assert reader.values().off_search_enabled is False
    finally:
        engine.dispose()


# ------------------------------------------------------------------------------------------
# AC5 (CLI side) invalid input exits non-zero and changes nothing


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["meal_planner", "true"], "unknown flag 'meal_planner'"),
        (["nope", "v1"], "unknown flag 'nope'"),
        (["progression_engine", "v3"], "invalid value for progression_engine"),
        (["off_search_enabled", "yes"], "invalid value for off_search_enabled"),
        (["fault_injection_latency_ms", "-5"], "invalid value for fault_injection_latency_ms"),
        (["fault_injection_latency_ms", "10001"], "invalid value for fault_injection_latency_ms"),
    ],
)
def test_cli_rejects_unknown_keys_and_invalid_values_without_changing_anything(
    db: Engine, migrated_database_url: str, args: list[str], message: str
) -> None:
    ok = run_cli(migrated_database_url, "set", "progression_engine", "v2", "--actor", "owner")
    assert ok.returncode == 0, ok.stderr
    before = rows(db)

    result = run_cli(migrated_database_url, "set", *args, "--actor", "oncall-agent")

    assert result.returncode == 2
    assert message in result.stderr and "nothing changed" in result.stderr
    assert rows(db) == before
    assert json_lines(result.stdout) == []  # no change logged


def test_cli_rejects_an_actor_that_could_be_an_email(
    db: Engine, migrated_database_url: str
) -> None:
    result = run_cli(
        migrated_database_url, "set", "progression_engine", "v2", "--actor", "ana@x.test"
    )
    assert result.returncode == 2
    assert "invalid actor" in result.stderr
    assert "ana@x.test" not in result.stderr
    assert rows(db) == {}


def test_cli_without_database_exits_1_and_hides_connection_details() -> None:
    url = "postgresql+psycopg://fitwise:s3cret-pw@127.0.0.1:1/fitwise?connect_timeout=1"
    result = run_cli(url, "set", "progression_engine", "v2", "--actor", "owner")
    assert result.returncode == 1
    assert "database error" in result.stderr and "nothing changed" in result.stderr
    assert "s3cret-pw" not in result.stderr + result.stdout


# ------------------------------------------------------------------------------------------
# AC6 audit: updated_by, updated_at (UTC), one structured log line


def test_cli_change_records_actor_and_utc_time_and_logs_one_line(
    db: Engine, migrated_database_url: str, tmp_path: Path
) -> None:
    log_file = tmp_path / "backend.log"
    started = dt.datetime.now(dt.UTC)
    result = run_cli(
        migrated_database_url,
        "set",
        "fault_injection_latency_ms",
        "1500",
        "--actor",
        "oncall-agent",
        "--log-stream",
        str(log_file),
    )
    assert result.returncode == 0, result.stderr
    assert "fault_injection_latency_ms: 0 -> 1500 (changed, by oncall-agent" in result.stdout

    row = rows(db)["fault_injection_latency_ms"]
    assert (row["value"], row["updated_by"]) == ("1500", "oncall-agent")
    assert row["updated_at"].tzinfo is not None  # timestamptz: an absolute UTC instant
    assert started - dt.timedelta(seconds=5) <= row["updated_at"] <= dt.datetime.now(dt.UTC)

    lines = json_lines(log_file.read_text())
    changes = [line for line in lines if line["message"] == "feature flag changed"]
    assert len(changes) == 1
    [change] = changes
    assert change["flag_key"] == "fault_injection_latency_ms"
    assert (change["flag_old_value"], change["flag_new_value"]) == ("0", "1500")
    assert change["actor"] == "oncall-agent"
    assert change["level"] == "info"
    # Nothing user-related, and no connection details.
    assert not {"user_hash", "user_id", "email", "name"} & set(change)
    assert "postgresql" not in log_file.read_text()


def test_second_change_logs_old_and_new_and_overwrites_the_audit_fields(
    db: Engine, migrated_database_url: str, json_logs: JsonLogs
) -> None:
    session_factory = make_session_factory(db)
    with session_factory() as session:
        set_flag(session, "progression_engine", "v2", "owner", NOW)
    later = NOW + dt.timedelta(hours=1)
    with session_factory() as session:
        change = set_flag(session, "progression_engine", "v1", "oncall-agent", later.astimezone())

    assert (change.old_value, change.new_value, change.changed) == ("v2", "v1", True)
    row = rows(db)["progression_engine"]
    assert (row["value"], row["updated_by"], row["updated_at"]) == ("v1", "oncall-agent", later)
    logged = json_logs.with_message("feature flag changed")
    assert [(x["flag_old_value"], x["flag_new_value"], x["actor"]) for x in logged] == [
        ("v1", "v2", "owner"),
        ("v2", "v1", "oncall-agent"),
    ]


def test_cli_list_shows_effective_values_and_who_set_them(
    db: Engine, migrated_database_url: str
) -> None:
    insert_raw(db, "progression_engine", "v9")
    assert (
        run_cli(
            migrated_database_url, "set", "off_search_enabled", "false", "--actor", "owner"
        ).returncode
        == 0
    )

    result = run_cli(migrated_database_url, "list")
    assert result.returncode == 0, result.stderr
    lines = {line.split("\t")[0]: line for line in result.stdout.splitlines()}
    assert lines["fault_injection_latency_ms"] == "fault_injection_latency_ms\t0\t(default)"
    assert lines["off_search_enabled"].startswith("off_search_enabled\tfalse\tset by owner at ")
    assert lines["progression_engine"].startswith("progression_engine\tv1\t")
    assert "default used" in lines["progression_engine"]


# ------------------------------------------------------------------------------------------
# AC7 the latency flag, set through the CLI, delays only the logging routes of the running app


def test_latency_flag_set_by_cli_delays_logging_routes_only(
    api: Api, migrated_database_url: str
) -> None:
    router = APIRouter()
    for path in ["/api/v1/sessions/{sid}/sets", "/api/v1/sessions/{sid}/move"]:
        router.add_api_route(path, lambda: {"ok": True}, methods=["POST"])
    api.app.include_router(router)
    client = TestClient(api.app)

    def timed(path: str) -> float:
        start = time.perf_counter()
        assert client.post(path).status_code == 200
        return time.perf_counter() - start

    assert timed("/api/v1/sessions/a/sets") < 0.3  # default 0: no delay

    result = run_cli(
        migrated_database_url, "set", "fault_injection_latency_ms", "400", "--actor", "owner"
    )
    assert result.returncode == 0, result.stderr
    api.clock.advance(seconds=FLAG_CACHE_TTL_SECONDS)

    assert timed("/api/v1/sessions/a/sets") >= 0.4
    assert timed("/api/v1/sessions/a/move") < 0.3

    assert (
        run_cli(
            migrated_database_url,
            "set",
            "fault_injection_latency_ms",
            "0",
            "--actor",
            "oncall-agent",
        ).returncode
        == 0
    )
    api.clock.advance(seconds=FLAG_CACHE_TTL_SECONDS)
    assert timed("/api/v1/sessions/a/sets") < 0.3
