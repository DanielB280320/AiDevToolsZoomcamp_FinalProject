"""Telemetry: OpenTelemetry traces and metrics, allow-listed JSON logs (spec §14, §6.5).

Wiring lives in `install_telemetry`; feature code uses:

* `get_logger(__name__)` for logs (keyword fields, allow-listed),
* `bind_user(user_id)` once a request is authenticated (adds `user_hash`),
* `request.app.state.telemetry.metrics` for the §14 counters and
  `request.app.state.telemetry.engine_span("progression")` around engine calls,
* `instrument_http_client(client, telemetry)` for outgoing httpx clients.
"""

from fastapi import FastAPI
from sqlalchemy import Engine

from app.telemetry.logs import bind_user, configure_logging, get_logger
from app.telemetry.middleware import RequestTelemetryMiddleware
from app.telemetry.setup import (
    SERVICE_NAME,
    Telemetry,
    build_telemetry,
    instrument_engine,
    instrument_fastapi,
    instrument_http_client,
)


def install_telemetry(app: FastAPI, engine: Engine, telemetry: Telemetry) -> None:
    """Instrument `app` and `engine`. Call after `install_error_handlers` so the request
    middleware wraps the 500 handler and records the final status."""
    app.state.telemetry = telemetry
    instrument_engine(engine, telemetry)
    app.add_middleware(RequestTelemetryMiddleware, routes=app.router.routes, telemetry=telemetry)
    instrument_fastapi(app, telemetry)


__all__ = [
    "SERVICE_NAME",
    "Telemetry",
    "bind_user",
    "build_telemetry",
    "configure_logging",
    "get_logger",
    "install_telemetry",
    "instrument_http_client",
]
