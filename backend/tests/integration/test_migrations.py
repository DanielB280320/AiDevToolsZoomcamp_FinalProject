import os
import subprocess
import sys

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
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
    """Every table in the SQLAlchemy metadata exists after `upgrade head`."""
    engine = create_engine(migrated_database_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables


def test_migrations_match_the_models_exactly(migrated_database_url: str) -> None:
    """Alembic autogenerate finds nothing to add: every column, type, index and constraint in the
    models exists in the migrated schema (catches a model change without a migration)."""
    engine = create_engine(migrated_database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert diff == []


def test_users_table_has_the_spec_columns(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    engine.dispose()
    assert {
        "id",
        "email",
        "password_hash",
        "display_name",
        "role",
        "birth_date",
        "units",
        "timezone",
        "disclaimer_accepted_at",
    } <= columns
