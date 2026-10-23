"""Demo latency fault (spec §15.3 S3): delay the key-journey logging routes by a flag.

When `fault_injection_latency_ms` > 0, the logging routes watched by the §15.1 alerts
(`POST /sessions/*/sets`, `POST /sessions/*/finish`, `POST /athletes/*/meal-logs`) wait that
many milliseconds before being handled; every other route is untouched. The default 0 adds no
delay. The on-call mitigation is `oncall/ops/flag.sh fault_injection_latency_ms 0`.

It sits inside the telemetry middleware, so the delay shows up in `http_server_duration` and in
the server span exactly like a real slowdown. It writes no logs and reads nothing from the
request but its method and path (never the body, query or headers).
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Final

from anyio import to_thread
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.flags import FlagReader

_SEGMENT: Final = r"[^/]+"
LOGGING_ROUTES: Final = (
    re.compile(rf"/api/v1/sessions/{_SEGMENT}/sets"),
    re.compile(rf"/api/v1/sessions/{_SEGMENT}/finish"),
    re.compile(rf"/api/v1/athletes/{_SEGMENT}/meal-logs"),
)

Sleep = Callable[[float], Awaitable[object]]


def is_logging_route(method: str, path: str) -> bool:
    return method == "POST" and any(route.fullmatch(path) for route in LOGGING_ROUTES)


class FaultInjectionMiddleware:
    """Reads the flag from `app.state.flags` (cached, see `FlagReader`) on logging routes only."""

    def __init__(self, app: ASGIApp, *, sleep: Sleep = asyncio.sleep) -> None:
        self.app = app
        self.sleep = sleep

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and is_logging_route(scope["method"], scope["path"]):
            reader: FlagReader = scope["app"].state.flags
            # The reader may query the database (once per TTL): keep it off the event loop.
            values = await to_thread.run_sync(reader.values)
            if values.fault_injection_latency_ms > 0:
                await self.sleep(values.fault_injection_latency_ms / 1000)
        await self.app(scope, receive, send)
