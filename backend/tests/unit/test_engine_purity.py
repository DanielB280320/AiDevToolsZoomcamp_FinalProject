"""Guard rule 3 of CLAUDE.md: engines are pure (no DB, HTTP, clock, env or app layers)."""

import ast
from pathlib import Path

import pytest

import app.engines

ENGINES_DIR = Path(app.engines.__file__).parent
FORBIDDEN_MODULES = (
    "sqlalchemy",
    "alembic",
    "psycopg",
    "fastapi",
    "starlette",
    "httpx",
    "requests",
    "urllib",
    "socket",
    "os",
    "time",
    "random",
    "app.db",
    "app.config",
    "app.models",
    "app.services",
    "app.routers",
)
FORBIDDEN_CALLS = ("now", "today", "utcnow", "time", "getenv")


def _engine_files() -> list[Path]:
    return sorted(ENGINES_DIR.rglob("*.py"))


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if any(name == mod or name.startswith(mod + ".") for mod in FORBIDDEN_MODULES):
                found.append(f"imports {name}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in FORBIDDEN_CALLS
        ):
            found.append(f"calls .{node.func.attr}()")
    return found


def test_engines_package_exists_with_constants_module() -> None:
    assert (ENGINES_DIR / "constants.py").is_file()


@pytest.mark.parametrize("path", _engine_files(), ids=lambda p: p.name)
def test_engine_module_is_pure(path: Path) -> None:
    assert _violations(path) == []


def test_purity_check_detects_violations(tmp_path: Path) -> None:
    impure = tmp_path / "impure.py"
    impure.write_text("import sqlalchemy\nfrom datetime import datetime\nx = datetime.now()\n")
    assert _violations(impure) == ["imports sqlalchemy", "calls .now()"]
