"""Static guard for D50 / issue #82: the backend never migrates or seeds on start.

The image command and the compose `backend` service only start uvicorn; the compose `migrate`
service runs the step from the same image and the backend waits for it to exit 0. A rollback
can therefore start an older backend on a newer schema (spec §11, §13; ADR 0009).
"""

import json
import re
from typing import Any

import yaml
from alembic.script import ScriptDirectory

from app.migrate import pending_revisions
from app.migrations import ALEMBIC_DIR, BACKEND_DIR

REPO_ROOT = BACKEND_DIR.parent
FORBIDDEN = re.compile(r"alembic|app\.migrate|app\.seed|\bseed\b|upgrade", re.IGNORECASE)


def _compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text())
    return data


def _dockerfile_cmd() -> list[str]:
    lines = (BACKEND_DIR / "Dockerfile").read_text().splitlines()
    [cmd] = [line for line in lines if line.startswith("CMD ")]
    parsed: list[str] = json.loads(cmd.removeprefix("CMD "))  # exec form only, no shell
    return parsed


def test_image_command_only_starts_uvicorn() -> None:
    cmd = _dockerfile_cmd()
    assert cmd[0] == "uvicorn"
    assert not any(FORBIDDEN.search(part) for part in cmd), cmd
    entrypoints = [
        line
        for line in (BACKEND_DIR / "Dockerfile").read_text().splitlines()
        if line.startswith("ENTRYPOINT")
    ]
    assert entrypoints == []


def test_compose_backend_runs_no_migration_or_seed() -> None:
    backend = _compose()["services"]["backend"]
    for key in ("command", "entrypoint"):
        assert key not in backend or not FORBIDDEN.search(json.dumps(backend[key]))


def test_compose_backend_waits_for_the_migration_step_from_the_same_image() -> None:
    services = _compose()["services"]
    migrate, backend = services["migrate"], services["backend"]
    assert migrate["image"] == backend["image"]
    assert migrate["command"] == ["python", "-m", "app.migrate"]
    assert migrate["restart"] == "no"
    assert backend["depends_on"]["migrate"] == {"condition": "service_completed_successfully"}


def test_migration_step_gets_no_app_secrets() -> None:
    env = _compose()["services"]["migrate"]["environment"]
    assert "JWT_SECRET" not in env
    assert "USER_HASH_SALT" not in env


def test_pending_revisions_are_oldest_first_and_exclude_applied_ones() -> None:
    script = ScriptDirectory(str(ALEMBIC_DIR))
    ordered = [rev.revision for rev in script.walk_revisions()][::-1]
    assert pending_revisions(script, ()) == ordered
    assert pending_revisions(script, (ordered[0],)) == ordered[1:]
    assert pending_revisions(script, tuple(script.get_heads())) == []
