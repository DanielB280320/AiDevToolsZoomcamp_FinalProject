"""F4.1 seed entry point: reference data loaded by the one-shot migration step.

`python -m app.migrate` calls `run_seed` after `alembic upgrade head`. The backend never seeds
on start (spec §11, §13; D50, ADR 0009). Every loader must be idempotent, so running the step
again changes nothing (F4.1). Insert missing rows only; never update or delete user data.

New reference data adds its loader to `LOADERS` (foods before the meals that use them).
"""

from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session

from app.seed_exercises import load_exercises
from app.seed_foods import load_foods, load_meals
from app.telemetry import get_logger

# A loader inserts what is missing and returns the number of rows it inserted.
SeedLoader = Callable[[Session], int]

# (kind, loader) pairs, run in order in one transaction. `kind` appears in the step's logs.
LOADERS: Sequence[tuple[str, SeedLoader]] = (
    ("exercises", load_exercises),
    ("foods", load_foods),
    ("meals", load_meals),
)

logger = get_logger(__name__)


def run_seed(session: Session, loaders: Sequence[tuple[str, SeedLoader]] = LOADERS) -> int:
    """Run every loader and commit once. Returns the total number of rows inserted."""
    inserted = 0
    for kind, loader in loaders:
        count = loader(session)
        logger.info("seed loaded", kind=kind, count=count)
        inserted += count
    session.commit()
    return inserted
