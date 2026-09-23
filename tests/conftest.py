"""Shared fixtures.

Integration tests run against a real PostgreSQL with pgvector. A lighter
database would pass while testing none of the guarantees that live in Postgres
itself, such as append-only logs and immutable published versions.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from testcontainers.community.postgres import PostgresContainer

POSTGRES_IMAGE = "pgvector/pgvector:pg17"


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer) -> str:
    return postgres.get_connection_url()
