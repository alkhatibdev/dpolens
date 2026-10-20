"""Database sessions for the engine."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import URL, Connection, Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from dpolens.settings import Settings

type DatabaseEngine = Engine
type EngineSession = Session
"""The database types under names of our own.

A surface can then annotate a session or an engine without importing the ORM,
which is a boundary CI enforces rather than a habit.
"""

REQUIRED_EXTENSIONS = {
    "vector": "pgvector, for meaning search",
    "pg_textsearch": "BM25 keyword ranking",
}


class MissingExtension(Exception):
    """The database cannot support retrieval as DPOLens performs it."""


class NotMigrated(Exception):
    """The extensions are available, but this database has not been set up yet."""


class DatabaseUnavailable(Exception):
    """The database would not take a connection, for a reason a person can fix."""


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
    with connect(engine) as connection:
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


def connect(engine: Engine) -> Connection:
    """A connection, or the reason there is none in words a person can act on.

    The driver names the address it tried and what the server said, and nothing
    about why a password that worked once stops working, which is the usual case.
    PostgreSQL sends no error code before a connection is established, so the
    cause is read from the server's message, and a message not recognised here is
    passed on as it is.
    """
    try:
        return engine.connect()
    except OperationalError as failed:
        raise DatabaseUnavailable(_why_not(str(failed.orig or failed), engine.url)) from failed


def _why_not(said: str, url: URL) -> str:
    where = f"{url.host}:{url.port or 5432}"
    if "password authentication failed" in said:
        return (
            f"the database at {where} refused the password for {url.username}. The "
            "database stores each role's password when it creates the role, and changing "
            "the configured password afterwards, for example by writing a new .env, does "
            "not change the stored one. Configure the password the database was created "
            "with, or set the new one in the database with ALTER ROLE. PostgreSQL refuses "
            "a role that does not exist the same way."
        )
    if 'database "' in said and "does not exist" in said:
        return (
            f'the server at {where} has no database named "{url.database}". Create it, '
            "or point the database URL at one that exists."
        )
    if "resolve host" in said or "translate host name" in said:
        return (
            f'the database host "{url.host}" has no address. Check the host in the '
            "database URL, and that the database is on the same network."
        )
    if any(sign in said for sign in ("Connection refused", "timed out", "timeout", "No route")):
        return (
            f"nothing answered at {where}. Check that the database is running and that "
            "the host and port in the database URL are right."
        )
    return f"could not connect to the database at {where} as {url.username}: {said}"


POOL_SIZE = 5
POOL_OVERFLOW = 10
"""SQLAlchemy's defaults, written out because the API works out from them how many
requests it runs at once."""


def create_db_engine(settings: Settings, verify: bool = True) -> Engine:
    engine = create_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        pool_size=POOL_SIZE,
        max_overflow=POOL_OVERFLOW,
    )
    if verify:
        check_extensions(engine)
    return engine


def ping(session: Session) -> None:
    """The cheapest proof that the database answers, for a readiness probe.

    It lives here because a surface must not import the ORM, and one statement
    is the whole of it.
    """
    session.execute(text("SELECT 1"))


@contextmanager
def session_from(engine: Engine) -> Iterator[Session]:
    """One session on an engine that outlives it, committing on success.

    This is what a server uses: the engine and its pool belong to the process,
    and a session belongs to one request.
    """
    with Session(engine) as session:
        yield session
        session.commit()


@contextmanager
def maintenance_scope(settings: Settings) -> Iterator[Session]:
    """A session for work that changes the schema, such as creating an index.

    PostgreSQL requires ownership of a table to create an index on it, and the
    application role deliberately owns nothing: that is what keeps it from
    rewriting the governance log. So index building connects as the role that
    owns the tables, the same one migrations use, and falls back to the ordinary
    URL on a development database where both are the same role.
    """
    settings_for_owner = settings.model_copy(
        update={"database_url": settings.migration_database_url or settings.database_url}
    )
    with session_scope(settings_for_owner) as session:
        yield session


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    """A session and an engine of its own, for a command that then exits.

    A server wants `session_from` instead, so that one pool serves every
    request rather than one pool per request.
    """
    engine = create_db_engine(settings)
    try:
        with session_from(engine) as session:
            yield session
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
