"""The one-shot migration step `python -m app.migrate` (issue #82, spec §11, §13, D50).

Against real Postgres: it migrates to head and then seeds; it is idempotent; a failing revision
exits non-zero, is named in the logs and leaks no data; a database ahead of this release fails
the step instead of being "migrated".
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import ProcessSettings
from app.migrate import run_migration_step
from app.migrations import ALEMBIC_DIR, BACKEND_DIR, load_migration_scripts
from app.seed_exercises import SEED_EXERCISES
from app.seed_foods import SEED_FOODS, SEED_MEALS
from tests.conftest import JsonLogs, unreachable_database_url

# A value that would be health data if it were a real row; it must never reach the logs.
LEAK_MARKER = "leakmarker-weight-81.5kg-ann@example.com"


def _settings(database_url: str) -> ProcessSettings:
    values: dict[str, Any] = {"database_url": database_url, "app_env": "test"}
    return ProcessSettings(**values, _env_file=None)


def _versions(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        exists = connection.execute(text("SELECT to_regclass('alembic_version')")).scalar()
        rows = (
            set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if exists
            else set()
        )
    engine.dispose()
    return rows


def _heads() -> set[str]:
    return set(load_migration_scripts().heads)


def test_step_migrates_a_fresh_database_to_head_then_seeds(
    fresh_database_url: str, json_logs: JsonLogs
) -> None:
    seen_at_seed_time: list[set[str]] = []

    def probe_loader(session: Session) -> int:
        # The seed runs after the migrations: the schema is already at head.
        seen_at_seed_time.append(
            set(session.execute(text("SELECT version_num FROM alembic_version")).scalars())
        )
        return 0

    code = run_migration_step(_settings(fresh_database_url), loaders=[("probe", probe_loader)])

    assert code == 0
    assert _versions(fresh_database_url) == _heads()
    assert seen_at_seed_time == [_heads()]
    applied = [line["revision"] for line in json_logs.with_message("migration applied")]
    assert applied == [r.revision for r in _ordered_revisions()]
    assert [(line["kind"], line["count"]) for line in json_logs.with_message("seed loaded")] == [
        ("probe", 0)
    ]
    finished = json_logs.with_message("migration step finished")
    assert [line["revision"] for line in finished] == sorted(_heads())
    assert all(line["outcome"] == "ok" for line in finished)


def test_step_is_idempotent_and_the_seed_inserts_nothing_twice(
    fresh_database_url: str, json_logs: JsonLogs
) -> None:
    rows: list[str] = []

    def once_loader(session: Session) -> int:
        # Idempotent like a real loader: insert only what is missing.
        session.execute(text("CREATE TABLE IF NOT EXISTS seed_probe (k text PRIMARY KEY)"))
        result: Any = session.execute(
            text("INSERT INTO seed_probe VALUES ('a') ON CONFLICT DO NOTHING")
        )
        inserted = result.rowcount
        rows.append(str(inserted))
        return int(inserted)

    loaders = [("probe", once_loader)]
    assert run_migration_step(_settings(fresh_database_url), loaders=loaders) == 0
    assert run_migration_step(_settings(fresh_database_url), loaders=loaders) == 0

    assert rows == ["1", "0"]
    assert _versions(fresh_database_url) == _heads()
    started = json_logs.with_message("migration step started")
    assert [line["count"] for line in started] == [len(_ordered_revisions()), 0]


def test_default_seed_hook_loads_the_exercise_catalog_once(
    fresh_database_url: str, json_logs: JsonLogs
) -> None:
    """The F4.1 hook runs after the migrations and inserts the seed exercises."""
    assert run_migration_step(_settings(fresh_database_url)) == 0
    meal_rows = len(SEED_MEALS) + sum(len(meal.items) for meal in SEED_MEALS)
    assert [line["count"] for line in json_logs.with_message("seed completed")] == [
        len(SEED_EXERCISES) + len(SEED_FOODS) + meal_rows
    ]


def test_a_failing_revision_fails_the_step_names_it_and_leaks_nothing(
    fresh_database_url: str, json_logs: JsonLogs, tmp_path: Path, capfd: Any
) -> None:
    scripts = _scripts_with_extra_revision(
        tmp_path,
        upgrade_sql=f"SELECT CAST('{LEAK_MARKER}' AS integer)",  # DataError quoting the value
    )

    code = run_migration_step(_settings(fresh_database_url), script_location=scripts)

    assert code == 1
    # Earlier revisions stay applied (each is backward compatible); the bad one rolled back.
    assert _versions(fresh_database_url) == _heads()
    failed = json_logs.with_message("migration failed")
    assert len(failed) == 1
    assert failed[0]["revision"] == "ffff00000082"
    assert failed[0]["error_type"] == "DataError"
    assert failed[0]["level"] == "error"
    assert not json_logs.with_message("seed completed")  # no seed after a failed migration
    out, err = capfd.readouterr()
    for text_ in (json_logs.text, out, err):
        assert LEAK_MARKER not in text_
        assert "81.5" not in text_
        assert "Traceback" not in text_


def test_a_database_ahead_of_this_release_fails_the_step_and_is_left_alone(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    """Running an older image's step on a newer schema must not 'migrate' it. A rollback skips
    the step (D50); if someone runs it anyway it fails loudly and changes nothing."""
    engine = create_engine(migrated_database_url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'abcdef999999'"))
    engine.dispose()

    assert run_migration_step(_settings(migrated_database_url)) == 1

    assert _versions(migrated_database_url) == {"abcdef999999"}
    [line] = json_logs.with_message(
        "migration step failed: database revision unknown to this release"
    )
    assert (line["outcome"], line["revision"]) == ("unknown_revision", "abcdef999999")


def test_unreachable_database_fails_the_step(json_logs: JsonLogs) -> None:
    values: dict[str, Any] = {
        "database_url": unreachable_database_url(),
        "database_connect_timeout_seconds": 1,
    }
    settings = ProcessSettings(**values, _env_file=None)
    assert run_migration_step(settings) == 1
    [line] = json_logs.with_message("migration step failed")
    assert line["kind"] == "database"
    assert line["error_type"] == "OperationalError"


def test_module_entry_point_migrates_and_logs_json_only(fresh_database_url: str) -> None:
    """`python -m app.migrate` as the compose `migrate` service runs it: env config only."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DATABASE_URL": fresh_database_url,
        "APP_ENV": "test",
        "LOG_LEVEL": "INFO",
        "APP_VERSION": "test-sha",
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.migrate"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _versions(fresh_database_url) == _heads()
    lines = [json.loads(line) for line in result.stdout.splitlines() if line]
    messages = [line["message"] for line in lines]
    assert messages[0] == "migration step started"
    assert "seed completed" in messages
    assert messages[-1] == "migration step finished"
    assert {line["service"] for line in lines} == {"fitwise-migrate"}
    assert {line["version"] for line in lines} == {"test-sha"}
    assert result.stderr == ""
    # Nothing from DATABASE_URL (it holds the database password) is logged.
    assert "postgresql" not in result.stdout


def _ordered_revisions() -> list[Any]:
    return list(reversed(list(ScriptDirectory(str(ALEMBIC_DIR)).walk_revisions())))


def _scripts_with_extra_revision(tmp_path: Path, *, upgrade_sql: str) -> Path:
    """A copy of the real alembic/ directory plus one new head revision `ffff00000082`."""
    target = tmp_path / "alembic"
    shutil.copytree(ALEMBIC_DIR, target, ignore=shutil.ignore_patterns("__pycache__"))
    [head] = load_migration_scripts().heads
    (target / "versions" / "29990101_ffff00000082_broken.py").write_text(
        f'''"""Broken test revision."""

from alembic import op

revision = "ffff00000082"
down_revision = "{head}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("{upgrade_sql}")


def downgrade() -> None:
    pass
'''
    )
    return target
