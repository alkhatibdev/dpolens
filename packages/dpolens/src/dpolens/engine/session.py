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


class NotMigrated(Exception):
    """The extensions are available, but this database has not been set up yet."""


def check_extensions(engine: Engine) -> None:
    """Refuse to run against a database that cannot rank properly.

    Both halves of retrieval are database extensions. Running without one means
    quietly returning worse results, which is harder to notice than a refusal.

    An extension that the server offers but this database has not created is a
    different problem with a different fix, so the two are reported separately:
    one needs a better image, the other needs the migrations.
    """
    with engine.connect() as connection:
        created = set(connection.scalars(text("SELECT extname FROM pg_extension")).all())
        available = set(connection.scalars(text("SELECT name FROM pg_available_extensions")).all())

    absent = {name: why for name, why in REQUIRED_EXTENSIONS.items() if name not in available}
    if absent:
        listed = ", ".join(f"{name} ({why})" for name, why in sorted(absent.items()))
        raise MissingExtension(
            f"this PostgreSQL server does not offer {listed}. Use the DPOLens Postgres "
            "image, which ships both, or install them into your own server. Note that "
            "pg_textsearch also has to be in shared_preload_libraries."
        )

    uncreated = sorted(name for name in REQUIRED_EXTENSIONS if name not in created)
    if uncreated:
        raise NotMigrated(
            f"this database has not created {', '.join(uncreated)} yet. "
            "Run `alembic upgrade head` to set it up."
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
