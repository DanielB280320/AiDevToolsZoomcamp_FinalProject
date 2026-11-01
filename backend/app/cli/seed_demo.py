"""Load the demo athlete and coach: `python -m app.cli.seed_demo` (`make seed-demo`, #51).

Run it after the migration step, never on app start (D50). Refuses to run when the environment
is `prod` (`APP_ENV` or `FITWISE_ENV`). Safe to run again: it changes nothing once the demo data
exists. Prints and logs counts only, no health data. Exit status: 0 done, 1 refused or failed.
"""

import os
import secrets
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.config import ProcessSettings, Settings
from app.db import make_engine, make_session_factory
from app.demo_seed import ATHLETE_EMAIL, COACH_EMAIL, DEMO_PASSWORD, seed_demo
from app.services.clock import SystemClock
from app.telemetry import SERVICE_NAME, build_telemetry, configure_logging, get_logger

logger = get_logger("app.cli.seed_demo")


def _env_names() -> set[str]:
    return {os.environ.get(key, "").strip().lower() for key in ("APP_ENV", "FITWISE_ENV")}


def main() -> int:
    if "prod" in _env_names():
        sys.stderr.write("error: seed-demo refuses to run in prod (it loads test accounts)\n")
        return 1
    try:
        settings = ProcessSettings()
    except Exception as exc:  # the message can quote the database URL
        sys.stderr.write(f"error: invalid settings ({type(exc).__name__})\n")
        return 1
    if settings.app_env == "prod":
        sys.stderr.write("error: seed-demo refuses to run in prod (it loads test accounts)\n")
        return 1
    configure_logging(
        level=settings.log_level,
        env=settings.app_env,
        service=SERVICE_NAME,
        version=settings.app_version,
    )
    # Services need a Telemetry object; this one has random keys and no exporter, so nothing
    # leaves the process and no real signing key or salt is needed to seed.
    telemetry = build_telemetry(
        Settings(
            jwt_secret=secrets.token_urlsafe(32),  # type: ignore[arg-type]
            user_hash_salt=secrets.token_urlsafe(32),  # type: ignore[arg-type]
            otel_exporter_otlp_endpoint=None,
        )
    )
    engine = make_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            result, wrote = seed_demo(session, SystemClock().now(), telemetry)
    except (SQLAlchemyError, RuntimeError) as exc:
        logger.error(
            "demo seed failed", kind="demo_seed", outcome="failed", error_type=type(exc).__name__
        )
        sys.stderr.write(
            f"error: demo seed failed ({type(exc).__name__}); is the database migrated?\n"
        )
        return 1
    finally:
        engine.dispose()
        telemetry.shutdown()
    for kind, count in vars(result).items():
        logger.info("demo seed counts", kind=f"demo_{kind}", count=count)
    sys.stdout.write(
        ("demo data created" if wrote else "demo data already present") + "\n"
        f"  athlete: {ATHLETE_EMAIL}\n  coach:   {COACH_EMAIL}\n  password: {DEMO_PASSWORD}\n"
    )
    for kind, count in vars(result).items():
        sys.stdout.write(f"  {kind}: {count}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
