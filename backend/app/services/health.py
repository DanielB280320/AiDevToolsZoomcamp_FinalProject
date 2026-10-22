"""Readiness checks for `GET /readyz` (database reachable, migrations applied)."""

from collections.abc import Collection
from typing import Literal

from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.migrations import MigrationScripts
from app.schemas.health import Readiness, ReadinessChecks
from app.telemetry import get_logger

MigrationState = Literal["ok", "pending"]

logger = get_logger(__name__)


def migration_state(
    current: Collection[str], heads: Collection[str], known: Collection[str]
) -> MigrationState:
    """Compare the database's Alembic revisions with this release's scripts.

    * every head applied -> ok
    * nothing applied, or an older revision this release knows -> pending
    * only revisions this release does not know -> ok: the database is ahead because a newer
      release migrated it and this one was rolled back. Migrations are expand-only and backward
      compatible (spec §13), so the older release can still serve traffic.
    """
    if set(heads) <= set(current):
        return "ok"
    if not current:
        return "pending"
    if any(revision in known for revision in current):
        return "pending"
    return "ok"


def check_readiness(engine: Engine, scripts: MigrationScripts) -> Readiness:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = MigrationContext.configure(connection).get_current_heads()
    except SQLAlchemyError as exc:
        # The type only: driver messages can include the host, user or a query.
        logger.warning("readiness check failed", check="database", error_type=type(exc).__name__)
        return Readiness(status="unavailable", checks=ReadinessChecks(database="fail"))

    migrations = migration_state(current, scripts.heads, scripts.known)
    if migrations != "ok":
        logger.warning("readiness check failed", check="migrations", outcome=migrations)
    return Readiness(
        status="ok" if migrations == "ok" else "unavailable",
        checks=ReadinessChecks(database="ok", migrations=migrations),
    )
