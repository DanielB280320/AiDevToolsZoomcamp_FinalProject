"""One-shot migration step: `python -m app.migrate` (spec §11, §13; D50, ADR 0009).

Applies the pending Alembic revisions of this image, then runs the F4.1 seed hook, then exits:

* exit 0: the schema is at this release's head and the seed has run;
* exit 1: something failed; the backend must not be started on this image.

This is the only place migrations or the seed run. The backend container only starts the app,
so a rollback (previous image, newer schema) never touches the schema. Compose runs this as the
`migrate` service before `backend`; a rollback starts `backend` with `--no-deps`, skipping it.

Revisions are applied one at a time, each in its own transaction, so the logs name the revision
that failed. A failed revision is rolled back and earlier ones stay applied: each is backward
compatible (expand -> migrate -> contract), so the previous release still runs on them.

Logs are the app's allow-listed JSON: the revision id, counts and the exception class name.
Never the exception message or a traceback, because a database error can quote row values
(CLAUDE.md rule 6).
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from sqlalchemy.orm import Session

from app.config import ProcessSettings
from app.db import make_engine
from app.migrations import ALEMBIC_DIR, ALEMBIC_INI
from app.seed import LOADERS, SeedLoader, run_seed
from app.telemetry import configure_logging, get_logger

SERVICE_NAME: Final = "fitwise-migrate"

# Not __name__: under `python -m app.migrate` that is "__main__", outside the "app" logger tree.
logger = get_logger("app.migrate")


def _alembic_config(database_url: str, script_location: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(script_location))
    config.attributes["database_url"] = database_url
    # Alembic's fileConfig would add a plain-text handler next to the JSON one.
    config.attributes["configure_logger"] = False
    return config


def pending_revisions(script: ScriptDirectory, current: Sequence[str]) -> list[str]:
    """Revisions between the database's current heads and this release's heads, oldest first.

    Raises `RevisionError` when the database holds a revision this release does not know: a
    newer release migrated it (run the newer image's step instead) or it is the wrong database.
    """
    lower: str | tuple[str, ...] = tuple(current) if current else "base"
    return [rev.revision for rev in script.iterate_revisions("heads", lower)][::-1]


def run_migration_step(
    settings: ProcessSettings,
    *,
    script_location: Path = ALEMBIC_DIR,
    loaders: Sequence[tuple[str, SeedLoader]] = LOADERS,
) -> int:
    """Migrate to head, then seed. Returns the process exit code (0 ok, 1 failed)."""
    database_url = settings.database_url.get_secret_value()
    config = _alembic_config(database_url, script_location)
    script = ScriptDirectory.from_config(config)
    engine = make_engine(settings)
    try:
        try:
            with engine.connect() as connection:
                current = MigrationContext.configure(connection).get_current_heads()
        except Exception as exc:
            logger.error("migration step failed", kind="database", error_type=type(exc).__name__)
            return 1

        try:
            pending = pending_revisions(script, current)
        except RevisionError as exc:
            for revision in current:
                logger.error(
                    "migration step failed: database revision unknown to this release",
                    kind="migration",
                    outcome="unknown_revision",
                    revision=revision,
                    error_type=type(exc).__name__,
                )
            return 1

        logger.info("migration step started", kind="migration", count=len(pending))
        for revision in pending:
            try:
                command.upgrade(config, revision)
            except Exception as exc:
                logger.error(
                    "migration failed",
                    kind="migration",
                    outcome="failed",
                    revision=revision,
                    error_type=type(exc).__name__,
                )
                return 1
            logger.info("migration applied", kind="migration", revision=revision)

        try:
            with Session(engine) as session:
                inserted = run_seed(session, loaders)
        except Exception as exc:
            error_type = type(exc).__name__
            logger.error("seed failed", kind="seed", outcome="failed", error_type=error_type)
            return 1
        logger.info("seed completed", kind="seed", count=inserted)
    finally:
        engine.dispose()

    for head in sorted(script.get_heads()):
        logger.info("migration step finished", outcome="ok", revision=head, count=len(pending))
    return 0


def main() -> int:
    try:
        settings = ProcessSettings()  # DATABASE_URL etc. from the environment
    except Exception as exc:
        # hide_input_in_errors keeps the URL out of the message, but print the type only anyway.
        print(f"migration step: invalid settings ({type(exc).__name__})", file=sys.stderr)  # noqa: T201
        return 1
    configure_logging(
        level=settings.log_level,
        env=settings.app_env,
        service=SERVICE_NAME,
        version=settings.app_version,
    )
    return run_migration_step(settings)


if __name__ == "__main__":
    sys.exit(main())
