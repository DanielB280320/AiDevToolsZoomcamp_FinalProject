"""Per-request telemetry: route template, `http_server_duration`, access log, request context.

Runs inside the OpenTelemetry server span and outside `UnhandledErrorMiddleware`, so it sees the
final status (including 500) and its log line has the request's `trace_id`.

The access log replaces uvicorn's (which records the raw path and query string): route
template, method, status and duration only. Successful health probes are not logged.
"""

import time
from collections.abc import Sequence
from typing import Final

from fastapi.routing import iter_route_contexts
from opentelemetry import trace
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.telemetry.logs import (
    RequestContext,
    get_logger,
    reset_request_context,
    set_request_context,
)
from app.telemetry.metrics import UNMATCHED_ROUTE, normalize_method
from app.telemetry.setup import Telemetry

QUIET_ROUTES: Final = frozenset({"/api/v1/healthz", "/api/v1/readyz"})

access_log = get_logger("app.access")


def route_template(routes: Sequence[BaseRoute], scope: Scope) -> str | None:
    """The path template of the route that will handle `scope`, e.g. `/api/v1/x/{id}`.

    Routers added with `include_router` are nested (FastAPI >= 0.137); `iter_route_contexts`
    yields each route with its full, prefixed template. A partial match (right path, wrong
    method -> 405) still names the route. Unknown paths give None: the raw path is never used.
    """
    partial: str | None = None
    for route in iter_route_contexts(routes):
        match, _ = route.matches(scope)
        path = route.path
        if match is Match.FULL:
            return path
        if match is Match.PARTIAL and partial is None and path is not None:
            partial = path
    return partial


class RequestTelemetryMiddleware:
    def __init__(self, app: ASGIApp, *, routes: Sequence[BaseRoute], telemetry: Telemetry) -> None:
        self.app = app
        self.routes = routes
        self.telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        route = route_template(self.routes, scope)
        method = normalize_method(str(scope.get("method", "")))
        context = RequestContext(
            route=route,
            method=method,
            hash_user=self.telemetry.hash_user,
            server_span=trace.get_current_span(),
        )
        token = set_request_context(context)
        status = 500
        start = time.perf_counter()

        async def tracking_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        finally:
            seconds = time.perf_counter() - start
            self.telemetry.metrics.record_request(
                route=route, method=method, status=status, seconds=seconds
            )
            if not (route in QUIET_ROUTES and status < 400):
                access_log.info(
                    "request",
                    route=route or UNMATCHED_ROUTE,
                    method=method,
                    status=status,
                    duration_ms=round(seconds * 1000, 2),
                )
            reset_request_context(token)
