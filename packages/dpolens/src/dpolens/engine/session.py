"""Database sessions for the engine."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, text
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


class WritableGovernanceLog(Exception):
    """This connection could rewrite the governance log, so its promise is empty."""


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


GOVERNANCE_WRITES = ("UPDATE", "DELETE", "TRUNCATE")


def governance_log_is_append_only(bind: Engine | Connection) -> bool:
    """Whether this connection is actually unable to rewrite the governance log.

    A migration having once granted the right privileges is not evidence that
    they are still in place, and the log's whole value is that nobody can edit
    it, so the answer is asked of the database rather than assumed. It takes a
    session's connection as readily as an engine, so a surface can ask without
    opening a second one.
    """
    if isinstance(bind, Engine):
        with bind.connect() as connection:
            return _no_write_privileges(connection)
    return _no_write_privileges(bind)


def _no_write_privileges(connection: Connection) -> bool:
    privileges = ", ".join(f"'{name}'" for name in GOVERNANCE_WRITES)
    writable = connection.execute(
        text(
            "SELECT bool_or(has_table_privilege(current_user, 'governance_log', privilege)) "
            f"FROM unnest(ARRAY[{privileges}]) AS privilege"
        )
    ).scalar_one()
    return not bool(writable)


def check_governance_privileges(bind: Engine | Connection) -> None:
    """Refuse to serve where the governance log could be rewritten.

    The application role needs INSERT and SELECT on the log and nothing else.
    Connecting as the role that owns the tables leaves the log editable, which
    makes a tamper-evident log worth nothing, so a surface that serves other
    people stops here instead.
    """
    if governance_log_is_append_only(bind):
        return
    raise WritableGovernanceLog(
        "this connection holds UPDATE, DELETE or TRUNCATE on governance_log, so the "
        "log is not append-only for it. Connect as the application role that the "
        "migrations granted INSERT and SELECT, and run migrations as a separate "
        "owner role through DPOLENS_MIGRATION_DATABASE_URL."
    )
