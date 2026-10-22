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
        # Keeps bound parameters (emails, password hashes, body metrics) out of SQLAlchemy's SQL
        # logs and out of the "[parameters: ...]" part of its exception messages. It does NOT
        # cover the database's own error text: a Postgres error such as a duplicate-key violation
        # can still quote values ("Key (lower(email))=(...) already exists"), so exception
        # messages from the database must never be logged (spec §6.5); log `error_type` only.
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
