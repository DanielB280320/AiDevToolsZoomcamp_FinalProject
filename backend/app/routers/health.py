"""`GET /healthz` and `GET /readyz` (openapi.yaml, tag Ops)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas.health import Health, Readiness
from app.services.health import check_readiness

router = APIRouter(tags=["Ops"])


@router.get("/healthz", operation_id="getHealth", response_model=Health)
def get_health() -> Health:
    """Liveness: the process is up. Never touches the database."""
    return Health()


@router.get(
    "/readyz",
    operation_id="getReadiness",
    response_model=Readiness,
    responses={503: {"model": Readiness, "description": "Not ready."}},
)
def get_readiness(request: Request) -> JSONResponse:
    """Readiness: database reachable and migrations applied, else 503."""
    readiness = check_readiness(request.app.state.engine, request.app.state.migration_scripts)
    return JSONResponse(
        readiness.model_dump(exclude_none=True),
        status_code=200 if readiness.status == "ok" else 503,
    )
