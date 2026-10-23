"""`oncall/ops/flag.sh <key> <value>` (spec §15.2, issue #15).

`COMPOSE` is replaced by a fake that records its arguments and, for the expected
`exec -T backend python -m app.cli.flags ...` call, runs that same CLI on the host against the
test database: so these tests check both the exact container command and the end-to-end result
(allow-list, exit status, nothing changed on error) without Docker.
"""

import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text

from app.migrations import BACKEND_DIR

FLAG_SH = BACKEND_DIR.parent / "oncall" / "ops" / "flag.sh"
EXPECTED_PREFIX = ["exec", "-T", "backend", "python", "-m", "app.cli.flags", "set"]


@pytest.fixture
def db(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def fake_compose(tmp_path: Path) -> Path:
    """An executable standing in for `docker compose`; it logs argv to calls.log, one per line."""
    script = tmp_path / "fake-compose"
    script.write_text(
        f"""#!/usr/bin/env bash
set -eu
printf '%s\\n' "$@" > "{tmp_path}/calls.log"
[ "$1 $2 $3" = "exec -T backend" ] || {{ echo "fake compose: unexpected call" >&2; exit 97; }}
shift 3
[ "$1" = python ] || exit 98
shift
cd "{BACKEND_DIR}"
exec "{sys.executable}" "$@"
"""
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def run_flag_sh(
    fake_compose: Path, database_url: str, *args: str, **env: str
) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_", "FLAG_"))}
    return subprocess.run(
        [str(FLAG_SH), *args],
        env={**base, "COMPOSE": str(fake_compose), "DATABASE_URL": database_url, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def calls(fake_compose: Path) -> list[str] | None:
    log = fake_compose.parent / "calls.log"
    return log.read_text().splitlines() if log.exists() else None


def rows(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        result = connection.execute(text("SELECT key, value, updated_by FROM feature_flag"))
        return {key: (value, by) for key, value, by in result}


def test_script_is_executable() -> None:
    assert os.access(FLAG_SH, os.X_OK)


def test_runs_the_backend_cli_inside_the_backend_container(
    db: Engine, migrated_database_url: str, fake_compose: Path
) -> None:
    result = run_flag_sh(fake_compose, migrated_database_url, "progression_engine", "v2")

    assert result.returncode == 0, result.stderr
    assert calls(fake_compose) == [
        *EXPECTED_PREFIX,
        "progression_engine",
        "v2",
        "--actor",
        "oncall-agent",
        "--log-stream",
        "/proc/1/fd/1",
    ]
    assert "progression_engine: v1 -> v2 (changed, by oncall-agent" in result.stdout
    assert rows(db) == {"progression_engine": ("v2", "oncall-agent")}


def test_actor_can_be_set_for_a_human_operator(
    db: Engine, migrated_database_url: str, fake_compose: Path
) -> None:
    result = run_flag_sh(
        fake_compose, migrated_database_url, "fault_injection_latency_ms", "0", FLAG_ACTOR="owner"
    )
    assert result.returncode == 0, result.stderr
    assert rows(db) == {"fault_injection_latency_ms": ("0", "owner")}


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["meal_planner", "true"], "unknown flag"),
        (["database_url", "x"], "unknown flag"),
        (["progression_engine", "v3"], "invalid value for progression_engine"),
        (["off_search_enabled", "maybe"], "invalid value for off_search_enabled"),
        (["fault_injection_latency_ms", "99999"], "invalid value for fault_injection_latency_ms"),
    ],
)
def test_unknown_keys_and_invalid_values_exit_non_zero_and_change_nothing(
    db: Engine, migrated_database_url: str, fake_compose: Path, args: list[str], message: str
) -> None:
    assert (
        run_flag_sh(fake_compose, migrated_database_url, "progression_engine", "v2").returncode == 0
    )
    before = rows(db)

    result = run_flag_sh(fake_compose, migrated_database_url, *args)

    assert result.returncode != 0
    assert message in result.stderr and "nothing changed" in result.stderr
    assert rows(db) == before


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["progression_engine"],
        ["progression_engine", "v1", "extra"],
        ["progression_engine", "v1; rm -rf /"],
        ["progression_engine", "$(id)"],
        ["Progression_Engine", "v1"],
        ["progression_engine", ""],
        ["--help", "x"],
    ],
)
def test_malformed_arguments_are_rejected_before_reaching_the_container(
    db: Engine, migrated_database_url: str, fake_compose: Path, args: list[str]
) -> None:
    result = run_flag_sh(fake_compose, migrated_database_url, *args)

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert calls(fake_compose) is None  # compose was never invoked
    assert rows(db) == {}


def test_invalid_actor_from_the_environment_changes_nothing(
    db: Engine, migrated_database_url: str, fake_compose: Path
) -> None:
    result = run_flag_sh(
        fake_compose, migrated_database_url, "progression_engine", "v2", FLAG_ACTOR="ana@x.test"
    )
    assert result.returncode == 2
    assert "invalid actor" in result.stderr
    assert rows(db) == {}
