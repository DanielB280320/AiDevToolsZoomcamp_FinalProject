"""The app serves only operations that exist in `openapi.yaml`, under its `/api/v1` base path."""

from fastapi import FastAPI

from app.main import API_PREFIX
from tests.contract import contract

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _served_operations(app: FastAPI) -> dict[tuple[str, str], str]:
    """(method, contract path) -> operationId, from the app's generated OpenAPI document."""
    operations = {}
    for path, item in app.openapi()["paths"].items():
        assert path.startswith(API_PREFIX + "/"), path
        for method, operation in item.items():
            if method in HTTP_METHODS:
                operations[(method, path.removeprefix(API_PREFIX))] = operation["operationId"]
    return operations


def _contract_operations() -> dict[tuple[str, str], str]:
    return {
        (method, path): operation["operationId"]
        for path, item in contract()["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def test_contract_base_path_is_api_v1() -> None:
    assert [server["url"] for server in contract()["servers"]] == [API_PREFIX]


def test_contract_declares_the_probes() -> None:
    assert {("get", "/healthz"), ("get", "/readyz")} <= set(_contract_operations())


def test_every_served_operation_is_in_the_contract_with_its_operation_id(
    offline_app: FastAPI,
) -> None:
    served = _served_operations(offline_app)
    expected = _contract_operations()

    assert {("get", "/healthz"), ("get", "/readyz")} <= set(served)
    assert set(served) <= set(expected), set(served) - set(expected)
    for key, operation_id in served.items():
        assert operation_id == expected[key], key
