"""QA additions for issue #15 (feature flags): gaps not covered by the implementer's tests.

* `--log-stream` fallback: `flag.sh` always passes `/proc/1/fd/1`; if that cannot be opened the
  change must still apply and the audit line must still be written (to stdout), with no path or
  connection details in the warning.
* Privacy: a hand-written stored value outside the allow-list never reaches the change log line
  (the old value logged is the effective default), and the reader's warning names the key only.
* Fail-open: with the database unreachable, the real app's fault-injection middleware falls back
  to the default (0) and serves the logging routes without delay.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.db import make_session_factory
from app.migrations import BACKEND_DIR
from app.services.flags import FlagReader, set_flag
from tests.conftest import JsonLogs
from tests.integration.auth_helpers import NOW

SECRET_LOOKING_VALUE = "ana.lopez@example.test"  # what a careless hand edit could store


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    yield engine
    engine.dispose()


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


def stored(engine: Engine, key: str) -> tuple[str, str] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT value, updated_by FROM feature_flag WHERE key = :key"), {"key": key}
        ).one_or_none()
    return None if row is None else (row[0], row[1])


def test_unopenable_log_stream_still_applies_and_logs_the_change_to_stdout(
    db: Engine, migrated_database_url: str
) -> None:
    unopenable = "/nonexistent-qa77-dir/fd/1"
    result = run_cli(
        migrated_database_url,
        "set",
        "off_search_enabled",
        "false",
        "--actor",
        "oncall-agent",
        "--log-stream",
        unopenable,
    )

    assert result.returncode == 0, result.stderr
    assert "cannot open log stream" in result.stderr
    assert unopenable not in result.stderr  # the error type only, no path details
    changes = [x for x in json_lines(result.stdout) if x["message"] == "feature flag changed"]
    assert len(changes) == 1
    assert (changes[0]["flag_key"], changes[0]["flag_new_value"]) == ("off_search_enabled", "false")
    assert stored(db, "off_search_enabled") == ("false", "oncall-agent")


def test_invalid_hand_stored_value_never_reaches_the_logs(db: Engine, json_logs: JsonLogs) -> None:
    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO feature_flag (key, value, updated_by, updated_at) "
                "VALUES ('progression_engine', :value, 'owner', now())"
            ),
            {"value": SECRET_LOOKING_VALUE},
        )
    session_factory = make_session_factory(db)

    reader = FlagReader(session_factory, now=lambda: NOW)
    assert reader.values().progression_engine == "v1"  # F11.5 fallback
    with session_factory() as session:
        change = set_flag(session, "progression_engine", "v2", "oncall-agent", NOW)

    assert (change.old_value, change.new_value) == ("v1", "v2")  # effective, not the raw text
    [warning] = json_logs.with_message("feature flag invalid stored value")
    assert warning["flag_key"] == "progression_engine"
    [logged] = json_logs.with_message("feature flag changed")
    assert logged["flag_old_value"] == "v1"
    assert SECRET_LOOKING_VALUE not in json_logs.text
    assert "ana.lopez" not in json_logs.text


def test_unreachable_database_fails_open_with_no_delay(offline_app: FastAPI) -> None:
    """The real create_app wiring (real FlagReader, DB unreachable): no delay, request served."""
    router = APIRouter()
    router.add_api_route("/api/v1/sessions/{sid}/finish", lambda: {"ok": True}, methods=["POST"])
    offline_app.include_router(router)
    with TestClient(offline_app) as client:
        client.post("/api/v1/sessions/a/finish")  # first read may wait for the connect timeout
        start = time.perf_counter()
        response = client.post("/api/v1/sessions/a/finish")
        elapsed = time.perf_counter() - start
    assert response.status_code == 200
    assert elapsed < 0.3  # cached defaults within the TTL: latency 0, no repeated DB attempts
