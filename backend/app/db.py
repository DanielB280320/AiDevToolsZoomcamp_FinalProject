"""Database engine and session handling. Only services use sessions (architecture §2.1)."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DatabaseSettings


def make_engine(settings: DatabaseSettings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        # Bound parameters (emails, password hashes, body metrics) never reach SQL logs or
        # exception messages (spec §6.5).
        hide_parameters=True,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed by the service that uses it."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session
