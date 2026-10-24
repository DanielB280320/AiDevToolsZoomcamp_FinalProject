"""Latency fault injection on the §15.1 logging routes (spec §15.3 S3), with stub routes."""

import time

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.fault_injection import FaultInjectionMiddleware, is_logging_route
from app.services.flags import DEFAULT_FLAGS, FlagValues
from tests.conftest import JsonLogs

LOGGING_POSTS = [
    "/api/v1/sessions/1b4e28ba-2fa1-11d2-883f-0016d3cca427/sets",
    "/api/v1/sessions/abc/finish",
    "/api/v1/athletes/me/meal-logs",
    "/api/v1/athletes/1b4e28ba-2fa1-11d2-883f-0016d3cca427/meal-logs",
]
OTHER_POSTS = [
    "/api/v1/auth/login",
    "/api/v1/sessions/abc/sets/def",  # a set's own URL (PUT/DELETE in the contract)
    "/api/v1/sessions/abc/archive",
    "/api/v1/athletes/me/meal-logs/xyz",
    "/api/v1/athletes/me/body-metrics",
    "/api/v1/sessions//sets",  # an empty segment is not a session id
    "/sessions/abc/sets",  # outside the API prefix
    "/api/v1/sessions/abc/sets/",
]


class StubReader:
    def __init__(self, values: FlagValues = DEFAULT_FLAGS) -> None:
        self.flags = values
        self.calls = 0

    def values(self) -> FlagValues:
        self.calls += 1
        return self.flags


def with_latency(ms: int) -> FlagValues:
    return FlagValues(
        progression_engine="v1", off_search_enabled=True, fault_injection_latency_ms=ms
    )


def stub_router() -> APIRouter:
    router = APIRouter()

    def ok() -> dict[str, bool]:
        return {"ok": True}

    for path in [*LOGGING_POSTS, *OTHER_POSTS]:
        router.add_api_route(path, ok, methods=["POST", "GET", "PUT"])
    return router


def stub_app(reader: StubReader, sleeps: list[float]) -> FastAPI:
    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    app = FastAPI()
    app.state.flags = reader
    app.include_router(stub_router())
    app.add_middleware(FaultInjectionMiddleware, sleep=record)
    return app


@pytest.mark.parametrize("path", LOGGING_POSTS)
def test_logging_routes_are_delayed_by_the_flag(path: str) -> None:
    sleeps: list[float] = []
    with TestClient(stub_app(StubReader(with_latency(1500)), sleeps)) as client:
        assert client.post(path).status_code == 200
    assert sleeps == [1.5]


@pytest.mark.parametrize("path", OTHER_POSTS)
def test_other_routes_are_not_delayed_nor_read_the_flag(path: str) -> None:
    sleeps: list[float] = []
    reader = StubReader(with_latency(1500))
    with TestClient(stub_app(reader, sleeps)) as client:
        assert client.post(path).status_code in (200, 307)
    assert sleeps == []
    assert reader.calls == 0


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_only_post_is_delayed(method: str) -> None:
    sleeps: list[float] = []
    with TestClient(stub_app(StubReader(with_latency(1500)), sleeps)) as client:
        for path in LOGGING_POSTS:
            assert client.request(method, path).status_code == 200
    assert sleeps == []


def test_default_zero_adds_no_delay() -> None:
    sleeps: list[float] = []
    reader = StubReader()
    with TestClient(stub_app(reader, sleeps)) as client:
        for path in LOGGING_POSTS:
            assert client.post(path).status_code == 200
    assert sleeps == []
    assert reader.calls == len(LOGGING_POSTS)


def test_is_logging_route_table() -> None:
    assert all(is_logging_route("POST", path) for path in LOGGING_POSTS)
    assert not any(is_logging_route("POST", path) for path in OTHER_POSTS)
    assert not is_logging_route("GET", LOGGING_POSTS[0])


def test_the_app_wires_the_middleware_and_the_delay_is_measured(
    offline_app: FastAPI, json_logs: JsonLogs
) -> None:
    """create_app installs the middleware inside telemetry: the access log sees the delay."""
    offline_app.state.flags = StubReader(with_latency(300))
    offline_app.include_router(stub_router())
    with TestClient(offline_app) as client:
        start = time.perf_counter()
        assert client.post(LOGGING_POSTS[0]).status_code == 200
        delayed = time.perf_counter() - start
        start = time.perf_counter()
        assert client.post("/api/v1/sessions/abc/archive").status_code == 200
        undelayed = time.perf_counter() - start

    assert delayed >= 0.3
    assert undelayed < 0.3
    durations = {line["route"]: line["duration_ms"] for line in json_logs.with_message("request")}
    assert durations[LOGGING_POSTS[0]] >= 300
    assert durations["/api/v1/sessions/abc/archive"] < 300
    # The middleware itself writes nothing, so it cannot log request data.
    assert not [line for line in json_logs.lines() if line["logger"] == "app.fault_injection"]
