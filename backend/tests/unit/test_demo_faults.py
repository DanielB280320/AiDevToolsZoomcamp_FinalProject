"""S1 demo build fault (spec §15.3, D91): off when shipped; raises on `finish` if on and prod."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import demo_faults
from app.config import Settings
from app.errors import install_error_handlers
from app.routers import logging as logging_router
from tests.conftest import JsonLogs, make_settings

FINISH = f"/api/v1/sessions/{uuid.UUID(int=1)}/finish"
SETS = f"/api/v1/sessions/{uuid.UUID(int=1)}/sets"


def settings(app_env: str) -> Settings:
    return make_settings("postgresql+psycopg://x:x@127.0.0.1:1/x", app_env=app_env)


def client(app_env: str = "prod") -> TestClient:
    app = FastAPI()
    app.state.settings = settings(app_env)
    install_error_handlers(app)
    app.include_router(logging_router.router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


def test_shipped_build_has_no_demo_fault() -> None:
    # The fix PR for S1 flips the constant back; this keeps it from being merged on by accident.
    assert demo_faults.S1_FINISH_RAISES is False


def test_fault_off_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_faults, "S1_FINISH_RAISES", False)
    demo_faults.finish_session_fault(settings("prod"))


@pytest.mark.parametrize("app_env", ["local", "test", "dev"])
def test_fault_on_outside_prod_is_a_no_op(monkeypatch: pytest.MonkeyPatch, app_env: str) -> None:
    monkeypatch.setattr(demo_faults, "S1_FINISH_RAISES", True)
    demo_faults.finish_session_fault(settings(app_env))


def test_fault_on_raises_a_demo_fault_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_faults, "S1_FINISH_RAISES", True)
    with pytest.raises(demo_faults.DemoFaultError):
        demo_faults.finish_session_fault(settings("prod"))


def test_fault_on_makes_finish_answer_500_with_the_fault_class(
    monkeypatch: pytest.MonkeyPatch, json_logs: JsonLogs
) -> None:
    monkeypatch.setattr(demo_faults, "S1_FINISH_RAISES", True)
    response = client("prod").post(FINISH)
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    (line,) = json_logs.with_message("unhandled exception")
    assert line["error_type"] == "DemoFaultError"


@pytest.mark.parametrize("app_env", ["local", "test", "dev"])
def test_fault_on_outside_prod_finish_is_not_stopped_by_the_fault(
    monkeypatch: pytest.MonkeyPatch, json_logs: JsonLogs, app_env: str
) -> None:
    monkeypatch.setattr(demo_faults, "S1_FINISH_RAISES", True)
    client(app_env).post(FINISH)
    assert all(line.get("error_type") != "DemoFaultError" for line in json_logs.lines())


def test_fault_off_finish_is_not_stopped_by_the_fault(
    monkeypatch: pytest.MonkeyPatch, json_logs: JsonLogs
) -> None:
    monkeypatch.setattr(demo_faults, "S1_FINISH_RAISES", False)
    # This bare app has no database, so the route fails later for another reason; what matters is
    # that the fault is not what raised.
    client().post(FINISH)
    assert all(line.get("error_type") != "DemoFaultError" for line in json_logs.lines())


def test_only_finish_carries_the_fault_dependency() -> None:
    carriers = {
        route.path
        for route in logging_router.router.routes
        if isinstance(route, APIRoute)
        and any(d.call is demo_faults.finish_session_fault for d in route.dependant.dependencies)
    }
    assert carriers == {"/sessions/{session_id}/finish"}
