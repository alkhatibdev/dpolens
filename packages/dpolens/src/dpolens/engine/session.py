"""Database sessions for the engine."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from dpolens.settings import Settings


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(str(settings.database_url), pool_pre_ping=True)


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    """A session that commits on success and rolls back on failure."""
    engine = create_db_engine(settings)
    try:
        with Session(engine) as session:
            yield session
            session.commit()
    finally:
        engine.dispose()
