"""Database sessions for the engine."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from dpolens.settings import Settings

REQUIRED_EXTENSIONS = {
    "vector": "pgvector, for meaning search",
    "pg_textsearch": "BM25 keyword ranking",
}


class MissingExtension(Exception):
    """The database cannot support retrieval as DPOLens performs it."""


def check_extensions(engine: Engine) -> None:
    """Refuse to run against a database that cannot rank properly.

    Both halves of retrieval are database extensions. Running without one would
    mean quietly returning worse results, which is harder to notice than a
    refusal and worse for the person relying on them.
    """
    with engine.connect() as connection:
        installed = set(connection.scalars(text("SELECT extname FROM pg_extension")).all())

    missing = {name: why for name, why in REQUIRED_EXTENSIONS.items() if name not in installed}
    if missing:
        listed = ", ".join(f"{name} ({why})" for name, why in sorted(missing.items()))
        raise MissingExtension(
            f"this database is missing {listed}. Use the DPOLens Postgres image, "
            "which ships both, or install them into your own instance. Note that "
            "pg_textsearch also has to be in shared_preload_libraries."
        )


def create_db_engine(settings: Settings, verify: bool = True) -> Engine:
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    if verify:
        check_extensions(engine)
    return engine


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
