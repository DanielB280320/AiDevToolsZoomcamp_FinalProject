"""Validate payloads against the schemas in the repository's `openapi.yaml` (the API contract)."""

from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "openapi.yaml"
_CONTRACT_URI = "urn:fitwise:openapi"


@lru_cache
def contract() -> dict[str, Any]:
    with CONTRACT_PATH.open(encoding="utf-8") as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    return loaded


@lru_cache
def _registry() -> Registry[Any]:
    resource = DRAFT202012.create_resource(contract())
    return cast("Registry[Any]", Registry().with_resource(_CONTRACT_URI, resource))


def schema_validator(name: str) -> Draft202012Validator:
    """A validator for `#/components/schemas/<name>` with `$ref`s resolved inside the contract."""
    if name not in contract()["components"]["schemas"]:
        raise KeyError(f"schema {name!r} is not in openapi.yaml")
    return Draft202012Validator(
        {"$ref": f"{_CONTRACT_URI}#/components/schemas/{name}"},
        registry=_registry(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def assert_matches_schema(payload: Any, name: str) -> None:
    errors = sorted(schema_validator(name).iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, f"payload does not match {name}: " + "; ".join(e.message for e in errors)
