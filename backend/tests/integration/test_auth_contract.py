"""Responses of signUp, logIn, logOut, getMe and updateMe validate against openapi.yaml."""

import re
from typing import Any

from tests.contract import assert_matches_schema, contract
from tests.integration.auth_helpers import Api, problem

OPERATIONS = {
    ("post", "/auth/signup"): "signUp",
    ("post", "/auth/login"): "logIn",
    ("post", "/auth/logout"): "logOut",
    ("get", "/me"): "getMe",
    ("patch", "/me"): "updateMe",
}


def _documented_statuses(method: str, path: str) -> set[int]:
    return {int(status) for status in contract()["paths"][path][method]["responses"]}


def _check(method: str, path: str, response: Any) -> None:
    """Status is documented for the operation; body matches the documented schema."""
    assert response.status_code in _documented_statuses(method, path), (
        method,
        path,
        response.status_code,
    )
    if response.status_code == 204:
        assert response.content == b""
        return
    if response.status_code >= 400:
        assert response.headers["content-type"] == "application/problem+json"
        assert_matches_schema(response.json(), "Problem")
        return
    assert response.headers["content-type"] == "application/json"
    assert_matches_schema(response.json(), "Me")


def test_operation_ids_match_the_contract() -> None:
    for (method, path), operation_id in OPERATIONS.items():
        assert contract()["paths"][path][method]["operationId"] == operation_id


def test_every_response_of_the_five_operations_matches_the_contract(api: Api) -> None:
    calls: list[tuple[str, str, Any]] = []

    def call(method: str, path: str, client: Any = None, **kwargs: Any) -> Any:
        response = (client or api.client).request(method.upper(), "/api/v1" + path, **kwargs)
        calls.append((method, path, response))
        return response

    from tests.integration.auth_helpers import signup_body

    call("post", "/auth/signup", json=signup_body())  # 201
    call("post", "/auth/signup", json=signup_body())  # 409
    call("post", "/auth/signup", json=signup_body(accept_disclaimer=False))  # 422
    call("post", "/auth/signup", content=b"{", headers={"content-type": "application/json"})
    call("get", "/me")  # 200
    call("patch", "/me", json={"units": "imperial"})  # 200
    call("patch", "/me", json={})  # 422
    call("get", "/me", client=api.new_client())  # 401
    call("patch", "/me", client=api.new_client(), json={"units": "metric"})  # 401
    for _ in range(5):
        call("post", "/auth/login", json={"email": "ana@x.test", "password": "nope-nope-1"})
    limited = call("post", "/auth/login", json={"email": "ana@x.test", "password": "nope-nope-1"})
    call("post", "/auth/login", json={"email": "ana@x.test"})  # 422
    api.clock.advance(minutes=15)
    call("post", "/auth/login", json={"email": "ana@x.test", "password": "correct-horse-battery"})
    call("post", "/auth/logout")  # 204

    for method, path, response in calls:
        _check(method, path, response)
    statuses = {(m, p, r.status_code) for m, p, r in calls}
    assert {
        ("post", "/auth/signup", 201),
        ("post", "/auth/signup", 400),
        ("post", "/auth/signup", 409),
        ("post", "/auth/signup", 422),
        ("post", "/auth/login", 200),
        ("post", "/auth/login", 401),
        ("post", "/auth/login", 422),
        ("post", "/auth/login", 429),
        ("post", "/auth/logout", 204),
        ("get", "/me", 200),
        ("get", "/me", 401),
        ("patch", "/me", 200),
        ("patch", "/me", 401),
        ("patch", "/me", 422),
    } <= statuses

    problem(limited, 429, "rate_limited")
    retry_after = limited.headers["retry-after"]
    assert re.fullmatch(r"[1-9][0-9]*", retry_after)  # RetryAfter: integer >= 1
