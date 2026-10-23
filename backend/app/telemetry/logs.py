"""Allow-listed JSON logging to stdout (spec §14 Logs, §6.5).

Use `get_logger(__name__)` and pass data as keyword fields; the message is a constant:

    log = get_logger(__name__)
    log.info("set logged", outcome="created")

* Only fields in `privacy.LOG_EVENT_FIELDS` are kept; anything else (an email, a weight, a note,
  an unknown key) is dropped before it reaches any handler.
* `%`-style arguments are never interpolated, so `logger.info("user %s", email)` from any library
  logs the template only. Free text is scrubbed for emails/tokens and capped.
* Tracebacks are never written; an exception contributes its class name as `error_type`.
* Each line carries `trace_id`/`span_id` of the active span, `env`, `service`, `version`, and the
  `route` template and `user_hash` of the current request.
"""

import json
import logging
import sys
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, TextIO
from uuid import UUID

from opentelemetry import trace

from app.telemetry.privacy import LOG_BASE_FIELDS, LOG_EVENT_FIELDS, filter_log_fields, scrub_text

_HANDLER_MARKER: Final = "_fitwise_json_handler"
# Library loggers routed through the JSON handler. `uvicorn.access` is disabled: its lines hold
# the raw path and query string. `RequestTelemetryMiddleware` writes the allow-listed access log.
_ROUTED_LOGGERS: Final = ("uvicorn", "uvicorn.error", "sqlalchemy", "alembic")
_SILENCED_LOGGERS: Final = ("uvicorn.access",)


@dataclass
class RequestContext:
    """Per-request telemetry state, shared by reference with threadpool workers."""

    route: str | None
    method: str
    hash_user: Callable[[UUID | str], str]
    server_span: trace.Span = field(default_factory=trace.get_current_span)
    user_hash: str | None = field(default=None)


_request_context: ContextVar[RequestContext | None] = ContextVar(
    "fitwise_request_context", default=None
)


def current_request_context() -> RequestContext | None:
    return _request_context.get()


def set_request_context(context: RequestContext | None) -> object:
    return _request_context.set(context)


def reset_request_context(token: object) -> None:
    _request_context.reset(token)  # type: ignore[arg-type]


def bind_user(user_id: UUID | str) -> str | None:
    """Attach the signed-in user to the current request's logs and server span, as `user_hash`.

    Call it once the request is authenticated (the auth dependency does). Returns the hash, or
    None outside a request.
    """
    context = _request_context.get()
    if context is None:
        return None
    context.user_hash = context.hash_user(user_id)
    if context.server_span.is_recording():
        context.server_span.set_attribute("user_hash", context.user_hash)
    return context.user_hash


class JsonFormatter(logging.Formatter):
    """One JSON object per line with allow-listed fields only."""

    def __init__(self, *, env: str, service: str, version: str) -> None:
        super().__init__()
        self._static = {"env": env, "service": service, "version": version}

    def format(self, record: logging.LogRecord) -> str:
        span_context = trace.get_current_span().get_span_context()
        valid = span_context.is_valid
        line: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "message": _message(record),
            "logger": record.name,
            "trace_id": format(span_context.trace_id, "032x") if valid else None,
            "span_id": format(span_context.span_id, "016x") if valid else None,
            **self._static,
        }
        context = _request_context.get()
        if context is not None:
            line["route"] = context.route
            if context.user_hash is not None:
                line["user_hash"] = context.user_hash
        line.update(filter_log_fields(record.__dict__))
        if record.exc_info and record.exc_info[0] is not None and "error_type" not in line:
            line["error_type"] = record.exc_info[0].__name__
        ordered = {key: line[key] for key in (*LOG_BASE_FIELDS, *sorted(line)) if key in line}
        return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))


def _message(record: logging.LogRecord) -> str:
    # The template only: `record.args` are never interpolated because they may hold user data.
    if isinstance(record.msg, str):
        return scrub_text(record.msg)
    return f"<{type(record.msg).__name__}>"


class StructuredLogger:
    """A thin wrapper over `logging.Logger` that only forwards allow-listed fields."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def log(self, level: int, message: str, /, **fields: object) -> None:
        if self._logger.isEnabledFor(level):
            # stacklevel 3: report the caller of debug()/info()/..., not this module.
            self._logger.log(level, message, extra=filter_log_fields(fields), stacklevel=3)

    def debug(self, message: str, /, **fields: object) -> None:
        self.log(logging.DEBUG, message, **fields)

    def info(self, message: str, /, **fields: object) -> None:
        self.log(logging.INFO, message, **fields)

    def warning(self, message: str, /, **fields: object) -> None:
        self.log(logging.WARNING, message, **fields)

    def error(self, message: str, /, **fields: object) -> None:
        self.log(logging.ERROR, message, **fields)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(logging.getLogger(name))


def configure_logging(
    *, level: str, env: str, service: str, version: str, stream: TextIO | None = None
) -> None:
    """Send the root logger (and uvicorn's) to stdout (or `stream`) as allow-listed JSON.
    Idempotent."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(env=env, service=service, version=version))
    setattr(handler, _HANDLER_MARKER, True)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    logging.getLogger("app").setLevel(level)

    for name in _ROUTED_LOGGERS:
        library_logger = logging.getLogger(name)
        library_logger.handlers.clear()
        library_logger.propagate = True
    for name in _SILENCED_LOGGERS:
        silenced = logging.getLogger(name)
        silenced.handlers.clear()
        silenced.propagate = False
        silenced.disabled = True


__all__ = [
    "LOG_EVENT_FIELDS",
    "JsonFormatter",
    "RequestContext",
    "StructuredLogger",
    "bind_user",
    "configure_logging",
    "current_request_context",
    "get_logger",
]
