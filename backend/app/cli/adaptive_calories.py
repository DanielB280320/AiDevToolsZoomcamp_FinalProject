"""Weekly adaptive-calorie job (spec F14, #42). Run on Mondays, e.g. from a timer:

    python -m app.cli.adaptive_calories

Creates a pending `calories` suggestion for each athlete whose last two complete weeks trend
outside the goal's band. Safe to run more than once a week: an athlete is evaluated once per
Monday. The database URL comes from `DATABASE_URL`. Prints only the number of suggestions
created (no health data). Exit status: 0 done, 1 configuration or database error.
"""

import sys
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import DatabaseSettings
from app.db import make_engine, make_session_factory
from app.services import adaptive_calories
from app.services.clock import SystemClock


def main(argv: Sequence[str] | None = None) -> int:
    try:
        settings = DatabaseSettings()
    except ValidationError:
        sys.stderr.write("error: DATABASE_URL is not configured\n")
        return 1
    engine = make_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            created = adaptive_calories.run_weekly(session, SystemClock().now())
    except SQLAlchemyError:
        sys.stderr.write("error: database error\n")
        return 1
    finally:
        engine.dispose()
    sys.stdout.write(f"adaptive calorie suggestions created: {created}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
