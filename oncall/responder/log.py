"""Structured JSON logging with an allow-list of fields (spec §6.5).

The responder handles alert metadata only, but it logs through this one function so a stray
field (an alert annotation, a header, a log line) can never reach the journal.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

ALLOWED_FIELDS = frozenset(
    {
        "alert_status",
        "alerts",
        "backend",
        "duration_ms",
        "error_type",
        "exit_code",
        "fingerprint",
        "incident_id",
        "launcher",
        "opened",
        "closed",
        "reason",
        "status_code",
    }
)

_logger = logging.getLogger("oncall")


class _StdoutHandler(logging.Handler):
    """Writes to whatever sys.stdout is at emit time (journald in prod, capture in tests)."""

    def emit(self, record: logging.LogRecord) -> None:
        print(self.format(record), file=sys.stdout, flush=True)  # noqa: T201


def configure() -> None:
    if _logger.handlers:
        return
    handler = _StdoutHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def log(event: str, **fields: object) -> None:
    record: dict[str, object] = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "service": "oncall",
        "event": event,
    }
    record.update({k: v for k, v in fields.items() if k in ALLOWED_FIELDS})
    _logger.info(json.dumps(record, default=str))
