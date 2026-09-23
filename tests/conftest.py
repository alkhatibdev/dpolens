"""Shared fixtures.

Integration tests run against a real PostgreSQL with pgvector. A lighter
database would pass while testing none of the guarantees that live in Postgres
itself, such as append-only logs and immutable published versions.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

POSTGRES_IMAGE = "pgvector/pgvector:pg17"
REPO_ROOT = Path(__file__).parents[1]
FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "packs"

TABLES = ("node_references", "node_texts", "document_nodes", "document_versions", "documents")


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer) -> str:
    return postgres.get_connection_url()


@pytest.fixture(scope="session")
def migrated(database_url: str) -> str:
    """Run the migrations once, the way an instance upgrades."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


@pytest.fixture(scope="session")
def engine(migrated: str) -> Iterator[Engine]:
    engine = create_engine(migrated)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
        session.rollback()

    # Published rows cannot be deleted, by design, so tests reset with TRUNCATE.
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))


@pytest.fixture
def testlaw_pack() -> Path:
    return FIXTURE_PACKS / "testlaw"
