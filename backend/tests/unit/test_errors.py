"""The shared RFC 9457 error handler (spec D40, openapi.yaml `Problem`)."""

import datetime as dt
import logging
from collections.abc import Iterator
from typing import Annotated, Any, Literal

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import Field

from app.errors import PROBLEM_MEDIA_TYPE, ProblemError
from app.schemas.base import RequestModel
from app.schemas.problem import FieldError
from tests.contract import assert_matches_schema

SECRET = "weight 84.2 kg secret-note"  # stands in for health data that must never leak


class BodyMetricIn(RequestModel):
    weight_kg: Annotated[float, Field(ge=35, le=300)]
    note: str
    units: Literal["metric", "imperial"] = "metric"


@pytest.fixture
def client(offline_app: FastAPI) -> Iterator[TestClient]:
    @offline_app.post("/api/v1/_test/body-metrics", status_code=201)
    def create_metric(body: BodyMetricIn) -> dict[str, float]:
        return {"weight_kg": body.weight_kg}

    @offline_app.get("/api/v1/_test/days/{day}")
    def get_day(day: dt.date, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict[str, str]:
        return {"date": day.isoformat()}

    @offline_app.get("/api/v1/_test/conflict")
    def conflict() -> None:
        raise ProblemError(
            409,
            "email_taken",
            "An account with this email already exists.",
            errors=[FieldError(field="email", code="taken", message="Already registered.")],
        )

    @offline_app.post("/api/v1/_test/boom")
    def boom(body: BodyMetricIn) -> None:
        raise RuntimeError(f"database said: {body.note}")

    with TestClient(offline_app) as test_client:
        yield test_client


def _problem(response_json: Any, status: int, code: str) -> dict[str, Any]:
    assert isinstance(response_json, dict)
    assert_matches_schema(response_json, "Problem")
    assert response_json["status"] == status
    assert response_json["code"] == code
    assert response_json["type"] == f"/problems/{code}"
    return response_json


def test_unknown_route_returns_404_not_found_problem(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = _problem(response.json(), 404, "not_found")
    assert body["title"] == "Not Found"


def test_wrong_method_returns_405_problem(client: TestClient) -> None:
    response = client.delete("/api/v1/healthz")

    assert response.status_code == 405
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert "GET" in response.headers["allow"]
    _problem(response.json(), 405, "method_not_allowed")


def test_body_validation_error_returns_422_with_field_errors(client: TestClient) -> None:
    response = client.post("/api/v1/_test/body-metrics", json={"weight_kg": 20, "units": "stone"})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = _problem(response.json(), 422, "validation_error")
    errors = {e["field"]: e for e in body["errors"]}
    assert errors["weight_kg"]["code"] == "out_of_range"
    assert errors["note"]["code"] == "required"
    assert errors["units"]["code"] == "invalid_choice"
    for error in errors.values():
        assert set(error) == {"field", "code", "message"}
        assert error["message"]


def test_unknown_body_property_is_rejected_with_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/_test/body-metrics", json={"weight_kg": 80, "note": "x", "is_admin": True}
    )

    assert response.status_code == 422
    body = _problem(response.json(), 422, "validation_error")
    assert body["errors"] == [
        {"field": "is_admin", "code": "unknown_field", "message": "Extra inputs are not permitted"}
    ]


def test_validation_errors_do_not_echo_submitted_values(client: TestClient) -> None:
    response = client.post(
        "/api/v1/_test/body-metrics",
        json={"weight_kg": SECRET, "note": "x", "units": SECRET, "extra": SECRET},
    )

    assert response.status_code == 422
    assert len(response.json()["errors"]) == 3
    assert "84.2" not in response.text
    assert "secret-note" not in response.text


def test_unparseable_json_returns_400_bad_request(client: TestClient) -> None:
    response = client.post(
        "/api/v1/_test/body-metrics",
        content=b'{"weight_kg": 80,',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    _problem(response.json(), 400, "bad_request")


@pytest.mark.parametrize(
    ("url", "field", "code"),
    [
        pytest.param("/api/v1/_test/days/not-a-date", "day", "invalid_format", id="path"),
        pytest.param("/api/v1/_test/days/2026-11-03?limit=0", "limit", "out_of_range", id="range"),
        pytest.param(
            "/api/v1/_test/days/2026-11-03?limit=abc", "limit", "invalid_format", id="type"
        ),
    ],
)
def test_invalid_parameter_returns_400_with_the_parameter_in_errors(
    client: TestClient, url: str, field: str, code: str
) -> None:
    response = client.get(url)

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = _problem(response.json(), 400, "bad_request")
    assert [(e["field"], e["code"]) for e in body["errors"]] == [(field, code)]


def test_problem_error_raised_by_a_service_is_rendered(client: TestClient) -> None:
    response = client.get("/api/v1/_test/conflict")

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": "/problems/email_taken",
        "title": "Conflict",
        "status": 409,
        "code": "email_taken",
        "detail": "An account with this email already exists.",
        "errors": [{"field": "email", "code": "taken", "message": "Already registered."}],
    }


def test_unhandled_exception_returns_bare_500_without_details(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    response = client.post("/api/v1/_test/boom", json={"weight_kg": 84.2, "note": SECRET})

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": "/problems/internal_error",
        "title": "Internal Server Error",
        "status": 500,
        "code": "internal_error",
        "detail": "Something went wrong on our side. Please try again later.",
    }
    _problem(response.json(), 500, "internal_error")
    for leaked in ("Traceback", "RuntimeError", "database said", "secret-note", "84.2"):
        assert leaked not in response.text
    # The log line names the exception type only, never its message or the request data.
    assert any(getattr(r, "error_type", None) == "RuntimeError" for r in caplog.records)
    assert "secret-note" not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)
