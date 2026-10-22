"""Integration tests run against a real PostgreSQL server given by TEST_DATABASE_URL.

Each test gets its own freshly created database, dropped afterwards, so tests never share
state and never touch a developer's data. The server is required: without it these tests
fail rather than skip, so CI can never go green without exercising Postgres.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from app.config import Settings
from app.migrations import ALEMBIC_INI


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration/" in item.nodeid:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def admin_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Point it at a throwaway PostgreSQL 16 server whose "
            "user may CREATE DATABASE (see backend/.env.example), or run only tests/unit."
        )
    return Settings(database_url=url, _env_file=None).database_url


@pytest.fixture
def fresh_database_url(admin_url: str) -> Iterator[str]:
    """URL of a new, empty database (no Alembic revision applied)."""
    name = f"fitwise_it_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def migrated_database_url(fresh_database_url: str) -> str:
    """URL of a new database upgraded to `head`."""
    command.upgrade(alembic_config(fresh_database_url), "head")
    return fresh_database_url
