"""Shared fixtures.

Integration tests run against a real PostgreSQL with pgvector. A lighter
database would pass while testing none of the guarantees that live in Postgres
itself, such as append-only logs and immutable published versions.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.applications import Starlette
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.image import DockerImage

from dpolens_mcp.api import Api
from dpolens_mcp.credential import Credential
from dpolens_mcp.main import asgi
from dpolens_mcp.settings import Settings
from dpolens_stub import DEVELOPER, HOST, SURFACE, Stub

REPO_ROOT = Path(__file__).parents[1]
POSTGRES_IMAGE = "dpolens-postgres:test"
APP_ROLE = "dpolens_app"
APP_PASSWORD = "dpolens_app_password"
COMMITTED_DB = "dpolens_committed"
FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "packs"

TABLES = (
    "node_embeddings",
    "embedding_models",
    "node_references",
    "node_texts",
    "document_nodes",
    "document_versions",
    "documents",
)


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """Postgres with pgvector and pg_textsearch, built from deploy/postgres.

    Built rather than pulled, so a contributor needs no registry access and the
    image always matches the Dockerfile in the branch they are on. Docker caches
    the layers, so this costs a second after the first run.
    """
    DockerImage(path=REPO_ROOT / "deploy" / "postgres", tag=POSTGRES_IMAGE).build()
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer) -> str:
    return postgres.get_connection_url()


@pytest.fixture(scope="session")
def app_role(database_url: str) -> str:
    """Create the role the application connects as, the way Compose does.

    Migrations never create roles, because a role is cluster-wide, so
    the tests stand in for the init script and then assert the privileges the
    migration granted.
    """
    engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": APP_ROLE}
            ).first()
            if exists is None:
                # CREATE ROLE takes no bind parameters, so the literal is spelled
                # out. Both values are test constants.
                connection.execute(
                    text(f"CREATE ROLE \"{APP_ROLE}\" LOGIN PASSWORD '{APP_PASSWORD}'")
                )
    finally:
        engine.dispose()
    return APP_ROLE


@pytest.fixture(scope="session")
def migrated(database_url: str, app_role: str) -> str:
    """Run the migrations once, the way an instance upgrades."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    # What `env.py` reads from the application's own URL in a real deployment.
    config.attributes["app_role"] = app_role
    command.upgrade(config, "head")
    return database_url


@pytest.fixture(scope="session")
def as_application() -> Callable[[str], str]:
    """Rewrite any database URL to connect as the restricted application role."""

    def rewrite(url: str) -> str:
        return (
            make_url(url)
            .set(username=APP_ROLE, password=APP_PASSWORD)
            .render_as_string(hide_password=False)
        )

    return rewrite


@pytest.fixture(scope="session")
def app_database_url(migrated: str, as_application: Callable[[str], str]) -> str:
    """The same database, reached as the restricted application role."""
    return as_application(migrated)


@pytest.fixture(scope="session")
def app_engine(app_database_url: str) -> Iterator[Engine]:
    engine = create_engine(app_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def unique() -> str:
    """A short suffix, because rows the governance log points at are never deleted."""
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def committed_owner_url(committed_database_url: str, database_url: str) -> str:
    """The committing tests' database, reached as the role that owns the tables.

    Creating an index needs ownership, which the application role deliberately
    does not have, so loading a corpus for a test connects the way an operator's
    maintenance command does.
    """
    owner = make_url(database_url)
    return (
        make_url(committed_database_url)
        .set(username=owner.username, password=owner.password)
        .render_as_string(hide_password=False)
    )


@pytest.fixture(scope="session")
def committed_database_url(database_url: str, app_role: str) -> str:
    """A database of its own for tests that commit, reached as the application role.

    The command line commits, by design, and the governance log cannot be
    emptied afterwards. Sharing one database would make every assertion about
    instance-wide state, such as who the last administrator is, depend on which
    test ran first.
    """
    server = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with server.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": COMMITTED_DB}
            ).first()
            if exists is None:
                connection.execute(text(f'CREATE DATABASE "{COMMITTED_DB}"'))
    finally:
        server.dispose()

    owner_url = make_url(database_url).set(database=COMMITTED_DB)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", owner_url.render_as_string(hide_password=False))
    config.attributes["app_role"] = app_role
    command.upgrade(config, "head")

    return owner_url.set(username=APP_ROLE, password=APP_PASSWORD).render_as_string(
        hide_password=False
    )


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


@pytest.fixture(scope="session")
def truncate_corpus(engine: Engine) -> Callable[[], None]:
    """Empty every corpus table, for fixtures that manage their own lifetime."""

    def empty() -> None:
        with engine.begin() as connection:
            connection.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))

    return empty


@pytest.fixture
def clean_tables(engine: Engine) -> Iterator[None]:
    """Empty the corpus after a test that wrote to it without a session fixture."""
    yield
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))


@pytest.fixture
def testlaw_pack() -> Path:
    return FIXTURE_PACKS / "testlaw"


@pytest.fixture
def bilingual_pack() -> Path:
    """Arabic prevails, with an official English translation under the same keys."""
    return FIXTURE_PACKS / "bilingual"


# The MCP server's tests drive the real server over a DPOLens instance that
# answers from canned bodies, which needs no database and no socket.
@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def surface_file(tmp_path: Path) -> Path:
    path = tmp_path / "surface-token"
    path.write_text(SURFACE + "\n", encoding="utf-8")
    return path


@pytest.fixture
def stub() -> Stub:
    return Stub()


@pytest.fixture
def settings(surface_file: Path) -> Settings:
    return Settings(
        api_url="http://api.invalid",  # type: ignore[arg-type]
        surface_token_file=surface_file,
        credential_wait_seconds=1,
    )


@pytest.fixture
def instance(settings: Settings, stub: Stub) -> Starlette:
    """The server as a container serves it, over the stub instance."""
    api = Api(
        base_url=settings.api,
        credential=Credential(settings.surface_token_file),
        timeout=5,
        transport=stub.transport,
    )
    return asgi(settings, api)


@pytest.fixture
async def running(instance: Starlette) -> AsyncIterator[Starlette]:
    """The app with its startup done, which is where the credential is read."""
    async with instance.router.lifespan_context(instance):
        yield instance


@pytest.fixture
async def over_http(running: Starlette) -> AsyncIterator[httpx2.AsyncClient]:
    """An ordinary HTTP client, for the questions that are about the door."""
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(running), base_url=HOST) as client:
        yield client


@pytest.fixture
async def connected(running: Starlette) -> AsyncIterator[Client]:
    """A real MCP client, presenting a developer's token the way a host does."""
    async with (
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(running),
            base_url=HOST,
            headers={"Authorization": f"Bearer {DEVELOPER}"},
        ) as http,
        Client(
            streamable_http_client(f"{HOST}/mcp", http_client=http), raise_exceptions=True
        ) as client,
    ):
        yield client
