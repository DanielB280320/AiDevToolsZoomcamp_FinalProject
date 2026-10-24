"""FastAPI app factory. Run with `uvicorn app.main:create_app --factory`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.errors import install_error_handlers
from app.fault_injection import FaultInjectionMiddleware
from app.migrations import load_migration_scripts
from app.routers import athletes, auth, exercises, health, me, plans
from app.services.clock import SystemClock
from app.services.flags import FlagReader
from app.telemetry import (
    SERVICE_NAME,
    Telemetry,
    build_telemetry,
    configure_logging,
    install_telemetry,
)

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, telemetry: Telemetry | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        level=settings.log_level,
        env=settings.app_env,
        service=SERVICE_NAME,
        version=settings.app_version,
    )
    telemetry = telemetry or build_telemetry(settings)

    # Creating the engine does not connect; /healthz works while the database is down.
    engine = make_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()
        telemetry.shutdown()

    app = FastAPI(
        title="FitWise API",
        version="1.0.0",
        # Not served in prod; openapi.yaml is the published contract.
        openapi_url=f"{API_PREFIX}/openapi.json" if settings.serves_api_docs else None,
        docs_url=f"{API_PREFIX}/docs" if settings.serves_api_docs else None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.migration_scripts = load_migration_scripts()
    app.state.clock = SystemClock()
    # Reads the clock through app.state so a test's FakeClock also drives the flag cache TTL.
    app.state.flags = FlagReader(app.state.session_factory, now=lambda: app.state.clock.now())

    # Innermost middleware: the injected delay is inside the error handler and the telemetry
    # middleware, so it is measured like real latency (spec §15.3 S3).
    app.add_middleware(FaultInjectionMiddleware)
    install_error_handlers(app)
    install_telemetry(app, engine, telemetry)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(me.router)
    api.include_router(exercises.router)
    api.include_router(plans.router)
    api.include_router(athletes.router)
    app.include_router(api)
    return app
