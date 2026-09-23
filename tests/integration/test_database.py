"""The test environment is a real Postgres with pgvector, not a stand-in.

Nothing here tests DPOLens yet. It proves the setup every later guarantee test
depends on: a container starts, the connection works, and pgvector is present.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


def test_connects_to_postgres(database_url: str) -> None:
    engine = create_engine(database_url)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


def test_pgvector_is_available(database_url: str) -> None:
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        installed = connection.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()

    assert installed == "vector"
