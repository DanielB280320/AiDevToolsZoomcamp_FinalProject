"""#102: a U+0000 in any request string is a client error (D40), never a 500 or a logged value.

The check is shared (`app.schemas.base`): request bodies reject it in every string field, query
parameters through the `NoNul` annotation, and the decoded cursor in the exercise service.
"""

import base64
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import Captured, JsonLogs, captured_telemetry, make_settings
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem, signup_body

URL = "/api/v1/exercises"
ME = "/api/v1/me"
NUL = "\x00"


def _exercise(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Sled push",
        "muscle_group": "quads",
        "equipment": "none",
        "type": "strength",
        "met": 6.5,
        "region": "lower",
    }
    body.update(overrides)
    return body


def _cursor(name: str) -> str:
    raw = json.dumps([name, str(uuid.uuid4())]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _fields(body: dict[str, Any]) -> set[str]:
    return {e["field"] for e in body["errors"]}


def test_query_parameters_with_nul_are_400_naming_the_parameter(api: Api) -> None:
    assert api.signup().status_code == 201
    for field, value in (("q", f"a{NUL}b"), ("cursor", _cursor(f"a{NUL}b")), ("cursor", f"a{NUL}")):
        body = problem(api.client.get(URL, params={field: value}), 400, "bad_request")
        assert field in _fields(body)


def test_a_nul_free_search_and_cursor_still_work(api: Api) -> None:
    assert api.signup().status_code == 201
    assert api.client.get(URL, params={"q": "ab", "cursor": _cursor("ab")}).status_code == 200


def test_custom_exercise_name_with_nul_is_422(api: Api) -> None:
    assert api.signup().status_code == 201
    body = problem(
        api.client.post(URL, json=_exercise(name=f"Sled{NUL}push")), 422, "validation_error"
    )
    assert "name" in _fields(body)
    assert api.client.post(URL, json=_exercise()).status_code == 201


@pytest.mark.parametrize("field", ["display_name", "email"])
def test_signup_with_nul_is_422_naming_the_field(api: Api, field: str) -> None:
    value = f"a{NUL}b" if field == "display_name" else f"a{NUL}b@x.test"
    body = problem(api.signup(**{field: value}), 422, "validation_error")
    assert field in _fields(body)
    assert api.signup().status_code == 201


def test_login_with_nul_in_email_is_422(api: Api) -> None:
    assert api.signup().status_code == 201
    body = problem(api.login(email=f"ana{NUL}@x.test"), 422, "validation_error")
    assert "email" in _fields(body)
    assert api.login().status_code == 200


@pytest.mark.parametrize("field", ["display_name", "timezone", "units"])
def test_patch_me_with_nul_is_422_naming_the_field(api: Api, field: str) -> None:
    assert api.signup().status_code == 201
    body = problem(api.client.patch(ME, json={field: f"a{NUL}b"}), 422, "validation_error")
    assert field in _fields(body)
    assert api.client.patch(ME, json={"display_name": "Ana B"}).status_code == 200


def test_a_nul_in_a_property_name_is_not_echoed(api: Api) -> None:
    assert api.signup().status_code == 201
    response = api.client.post(URL, json=_exercise(**{f"x{NUL}y": 1}))
    assert response.status_code == 422
    assert NUL not in response.text and "\\u0000" not in response.text


def test_nul_values_never_reach_responses_logs_or_spans(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, span_exporter, metric_reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    captured = Captured(app, telemetry, span_exporter, metric_reader)
    marker = "Zqxnulmarker"
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/signup", json=signup_body()).status_code == 201
        responses = [
            client.get(URL, params={"q": f"{marker}{NUL}"}),
            client.get(URL, params={"cursor": _cursor(f"{marker}{NUL}")}),
            client.post(URL, json=_exercise(name=f"{marker}{NUL}")),
            client.patch(ME, json={"display_name": f"{marker}{NUL}"}),
            client.post("/api/v1/auth/signup", json=signup_body(email=f"{marker}{NUL}@x.test")),
            client.post("/api/v1/auth/login", json={"email": f"{marker}{NUL}", "password": "x"}),
        ]
    assert [r.status_code for r in responses] == [400, 400, 422, 422, 422, 422]
    blobs = [r.text for r in responses] + [json_logs.text]
    blobs += [span.to_json() for span in captured.spans()]
    for blob in blobs:
        assert marker.lower() not in blob.lower()
        assert NUL not in blob and "\\u0000" not in blob
    assert "DataError" not in json_logs.text


def test_valid_unicode_is_still_accepted(api: Api) -> None:
    """QA #108: accents and emoji are not NUL and must keep working."""
    assert api.signup(display_name="Zoë Ñandú 🏋️").status_code == 201
    assert api.client.patch(ME, json={"display_name": "Ana 💪 Béla"}).status_code == 200
    created = api.client.post(URL, json=_exercise(name="Sentadilla búlgara 🦵"))
    assert created.status_code == 201
    assert api.client.get(URL, params={"q": "búlgara 🦵"}).status_code == 200


def test_all_request_models_inherit_the_nul_check() -> None:
    """QA #108: a request schema that bypasses RequestModel would skip the check."""
    import pydantic

    import app.schemas.exercises  # noqa: F401
    import app.schemas.users  # noqa: F401
    from app.schemas.base import RequestModel, ResponseModel

    def all_subclasses(cls: type) -> set[type]:
        return {s for c in cls.__subclasses__() for s in {c} | all_subclasses(c)}

    bypass = [
        c.__name__
        for c in all_subclasses(pydantic.BaseModel)
        if c.__module__.startswith("app.schemas")
        and not issubclass(c, (RequestModel, ResponseModel))
    ]
    assert bypass == []
