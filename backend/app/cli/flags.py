"""Feature-flag ops CLI (spec §15.2). Wrapped by `oncall/ops/flag.sh <key> <value>`.

    python -m app.cli.flags set <key> <value> --actor <label> [--log-stream PATH]
    python -m app.cli.flags list

* Only the allow-listed keys and values of `app.config.FEATURE_FLAGS` are accepted. An unknown
  key, an invalid value or an invalid actor exits with status 2 and a message on stderr
  **before** the database is opened, so nothing changes.
* No secrets in arguments: the database URL comes from `DATABASE_URL`, as for the app.
* Every `set` stores `updated_by` (the actor) and `updated_at` (UTC) and writes one JSON log
  line, `feature flag changed`, with `flag_key`, `flag_old_value`, `flag_new_value`, `actor`.
  `--log-stream /proc/1/fd/1` (what `flag.sh` passes) sends that line to the stdout of the
  container's main process, so it lands in the backend's log stream (and Loki) rather than
  only in the terminal of whoever ran the command. If the stream cannot be opened, the line
  goes to this process's stdout.
* Running backends pick the change up within `FLAG_CACHE_TTL_SECONDS` (no restart).

Exit status: 0 done, 1 configuration or database error, 2 invalid arguments.
"""

import argparse
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from typing import TextIO

from pydantic import Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import FEATURE_FLAGS, DatabaseSettings, Environment, LogLevel
from app.db import make_engine, make_session_factory
from app.models import FeatureFlag
from app.services.clock import SystemClock
from app.services.flags import (
    FlagError,
    describe_values,
    effective_value,
    set_flag,
    validate_change,
)
from app.telemetry import SERVICE_NAME, configure_logging

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


class OpsSettings(DatabaseSettings):
    """What the CLI needs from the environment: the database and the log-line labels only
    (no JWT secret, no telemetry salt)."""

    app_env: Environment = Field(default="local")
    app_version: str = Field(default="dev", min_length=1, max_length=64)
    log_level: LogLevel = Field(default="INFO")


def _parser() -> argparse.ArgumentParser:
    flags_help = "; ".join(
        f"{key}: {describe_values(spec)} (default {spec.default})"
        for key, spec in sorted(FEATURE_FLAGS.items())
    )
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.flags",
        description=f"Read or change FitWise feature flags. Allowed flags: {flags_help}.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    set_cmd = commands.add_parser("set", help="change one flag (audited)")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")
    set_cmd.add_argument(
        "--actor", required=True, help="who makes the change, e.g. oncall-agent or owner"
    )
    set_cmd.add_argument(
        "--log-stream",
        metavar="PATH",
        help="append the change's JSON log line here (e.g. /proc/1/fd/1); default stdout",
    )
    commands.add_parser("list", help="show every flag's effective value")
    return parser


def _open_log_stream(path: str | None, stack: ExitStack, stderr: TextIO) -> TextIO:
    if path is None:
        return sys.stdout
    try:
        return stack.enter_context(open(path, "a", encoding="utf-8"))
    except OSError as error:
        stderr.write(
            f"warning: cannot open log stream ({type(error).__name__}); logging to stdout\n"
        )
        return sys.stdout


def _cmd_set(args: argparse.Namespace, settings: OpsSettings, stderr: TextIO) -> int:
    with ExitStack() as stack:
        configure_logging(
            level=settings.log_level,
            env=settings.app_env,
            service=SERVICE_NAME,
            version=settings.app_version,
            stream=_open_log_stream(args.log_stream, stack, stderr),
        )
        engine = make_engine(settings)
        stack.callback(engine.dispose)
        with make_session_factory(engine)() as session:
            change = set_flag(session, args.key, args.value, args.actor, SystemClock().now())
    status = "changed" if change.changed else "unchanged"
    sys.stdout.write(
        f"{change.key}: {change.old_value} -> {change.new_value} ({status}, "
        f"by {change.actor} at {change.updated_at.isoformat().replace('+00:00', 'Z')})\n"
    )
    return EXIT_OK


def _cmd_list(settings: OpsSettings) -> int:
    engine = make_engine(settings)
    try:
        with make_session_factory(engine)() as session:
            rows = {row.key: row for row in session.query(FeatureFlag).all()}
    finally:
        engine.dispose()
    for key, spec in sorted(FEATURE_FLAGS.items()):
        row = rows.get(key)
        if row is None:
            sys.stdout.write(f"{key}\t{spec.default}\t(default)\n")
            continue
        value = effective_value(key, row.value)
        note = "" if value == row.value else "\t(stored value invalid, default used)"
        updated_at = row.updated_at.isoformat().replace("+00:00", "Z")
        sys.stdout.write(f"{key}\t{value}\tset by {row.updated_by} at {updated_at}{note}\n")
    return EXIT_OK


def main(argv: Sequence[str] | None = None, stderr: TextIO = sys.stderr) -> int:
    args = _parser().parse_args(argv)  # bad usage: argparse exits with status 2
    if args.command == "set":
        try:
            validate_change(args.key, args.value, args.actor)  # before any database access
        except FlagError as error:
            stderr.write(f"error: {error}; nothing changed\n")
            return EXIT_USAGE
    try:
        settings = OpsSettings()
    except ValidationError as error:
        names = ", ".join(sorted({str(e["loc"][0]).upper() for e in error.errors() if e["loc"]}))
        stderr.write(f"error: invalid or missing configuration: {names}\n")
        return EXIT_ERROR
    try:
        if args.command == "set":
            return _cmd_set(args, settings, stderr)
        return _cmd_list(settings)
    except SQLAlchemyError as error:
        # The type only: database messages can quote connection details.
        outcome = "; nothing changed" if args.command == "set" else ""
        stderr.write(f"error: database error ({type(error).__name__}){outcome}\n")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
