import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text

from app.migrations import BACKEND_DIR, load_migration_scripts
from app.models import Base


def _alembic_cli(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_alembic_upgrade_head_works_on_a_fresh_database(fresh_database_url: str) -> None:
    first = _alembic_cli(fresh_database_url, "upgrade", "head")
    assert first.returncode == 0, first.stderr
    again = _alembic_cli(fresh_database_url, "upgrade", "head")
    assert again.returncode == 0, again.stderr  # re-running is a no-op

    engine = create_engine(fresh_database_url)
    with engine.connect() as connection:
        applied = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    engine.dispose()
    assert applied == set(load_migration_scripts().heads)


def test_models_and_migrations_agree(migrated_database_url: str) -> None:
    """Every table in the SQLAlchemy metadata exists after `upgrade head` (none yet in M1)."""
    engine = create_engine(migrated_database_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables
