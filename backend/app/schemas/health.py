from typing import Literal

from app.schemas.base import ResponseModel


class Health(ResponseModel):
    """`Health` in openapi.yaml."""

    status: Literal["ok"] = "ok"


class ReadinessChecks(ResponseModel):
    database: Literal["ok", "fail"]
    migrations: Literal["ok", "pending"] | None = None


class Readiness(ResponseModel):
    """`Readiness` in openapi.yaml."""

    status: Literal["ok", "unavailable"]
    checks: ReadinessChecks
