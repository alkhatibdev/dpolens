"""The community version on a real instance: the Community account, made the same way on
every start, and a question asked with no token.

In a database of its own, so the account and its role never appear in another module's
lists of users and roles.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import Engine, create_engine, select
from typer.testing import CliRunner

from dpolens.api.app import create_app
from dpolens.cli.main import app as cli
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.community import COMMUNITY_EMAIL, COMMUNITY_ROLE, ensure_community
from dpolens.engine.auth.models import PersonalAccessToken
from dpolens.engine.auth.surface import ensure_surface
from dpolens.engine.auth.tokens import revoke_token
from dpolens.engine.auth.users import get_role, get_user
from dpolens.engine.documents.models import Document
from dpolens.engine.embedding import DEFAULT_MODEL, get_model
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.index import build_index
from dpolens.engine.logs.governance import Actor
from dpolens.engine.logs.models import QueryLogEntry
from dpolens.engine.packs.load import load_pack
from dpolens.engine.packs.selection import select_laws
from dpolens.engine.session import session_from
from dpolens.settings import Settings as EngineSettings
from dpolens_mcp.api import Api
from dpolens_mcp.credential import Credential
from dpolens_mcp.main import asgi
from dpolens_mcp.settings import Settings
from dpolens_stub import HOST, structured

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
TESTLAW = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"
runner = CliRunner()


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    """A community version's database: one law, chosen and indexed, and no policy."""
    app_url, owner_url = database_of_its_own("dpolens_community")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, TESTLAW)
        select_laws(opened, ["testlaw"], actor=ACTOR)
    with Embedder(get_model(DEFAULT_MODEL)) as embedder, session_from(owner) as opened:
        build_index(opened, embedder)
    yield app_url, owner
    owner.dispose()


@pytest.fixture(scope="module")
def named(own: tuple[str, Engine], tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The file the instance writes for the MCP server, on its first start."""
    path = tmp_path_factory.mktemp("community") / "community"
    with session_from(own[1]) as opened:
        ensure_community(opened, path=path, actor=ACTOR)
    return path


def ids(path: Path) -> tuple[str, str]:
    written = json.loads(path.read_text())
    return written["user"], written["token"]


def test_the_account_may_read_documents_and_nothing_else(
    own: tuple[str, Engine], named: Path
) -> None:
    with session_from(own[1]) as opened:
        role = get_role(opened, COMMUNITY_ROLE)
        user = get_user(opened, COMMUNITY_EMAIL)
        token = opened.scalars(
            select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
        ).one()

        assert role.permission_keys() == frozenset({"documents.read"})
        assert user.kind == "service_account"
        assert [held.name for held in user.roles] == [COMMUNITY_ROLE]
        assert token.permissions == ["documents.read"]
        assert not token.trusted_surface
        assert ids(named) == (str(user.id), str(token.id))


def test_running_it_again_keeps_what_works(own: tuple[str, Engine], named: Path) -> None:
    before = ids(named)

    with session_from(own[1]) as opened:
        again = ensure_community(opened, path=named, actor=ACTOR)

    assert not again.minted
    assert ids(named) == before


def test_a_revoked_token_is_replaced_and_the_file_follows(
    own: tuple[str, Engine], named: Path
) -> None:
    _, revoked = ids(named)
    with session_from(own[1]) as opened:
        token = opened.get(PersonalAccessToken, revoked)
        assert token is not None
        revoke_token(opened, token, actor=ACTOR)

    with session_from(own[1]) as opened:
        again = ensure_community(opened, path=named, actor=ACTOR)

    assert again.minted
    assert ids(named)[1] != revoked


def test_a_community_version_carries_no_sample_policy(
    own: tuple[str, Engine], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DPOLENS_DATABASE_URL", own[0])
    monkeypatch.setenv("DPOLENS_COMMUNITY", "true")

    result = runner.invoke(cli, ["policy", "sample"])

    assert result.exit_code == 0, result.output
    assert "A community version carries no sample policy." in result.output
    with session_from(own[1]) as opened:
        kinds = set(opened.scalars(select(Document.kind)))
    assert kinds == {"law"}


@pytest.fixture(scope="module")
async def running_api(own: tuple[str, Engine]) -> AsyncIterator[FastAPI]:
    api_app = create_app(EngineSettings.model_validate({"database_url": own[0]}))
    async with api_app.router.lifespan_context(api_app):
        yield api_app


@pytest.fixture(scope="module")
def surface(own: tuple[str, Engine], tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("surface") / "surface-token"
    with session_from(own[1]) as opened:
        ensure_surface(opened, path=path, actor=ACTOR, email="mcp-community@surface.invalid")
    return path


@pytest.mark.anyio
async def test_anyone_asks_without_a_token_and_is_logged_as_the_community_account(
    own: tuple[str, Engine], running_api: FastAPI, surface: Path, named: Path
) -> None:
    settings = Settings.model_validate(
        {
            "api_url": "http://api.invalid",
            "surface_token_file": surface,
            "credential_wait_seconds": 5,
            "community": True,
            "community_file": named,
            "DPOLENS_QUERY_LOG_RETENTION_DAYS": 30,
        }
    )
    api = Api(
        base_url=settings.api,
        credential=Credential(surface),
        timeout=30,
        transport=httpx2.ASGITransport(running_api),
    )
    mcp = asgi(settings, api)
    async with (
        mcp.router.lifespan_context(mcp),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(mcp), base_url=HOST) as http,
        Client(streamable_http_client(f"{HOST}/mcp", http_client=http)) as client,
    ):
        result = await client.call_tool("search_policies", {"query": "personal data"})

    assert result.is_error is False, result
    assert structured(result)["results"]
    with session_from(own[1]) as opened:
        community = get_user(opened, COMMUNITY_EMAIL)
        asked = opened.scalars(
            select(QueryLogEntry)
            .where(QueryLogEntry.operation == "search")
            .order_by(QueryLogEntry.created_at.desc())
        ).first()
        assert asked is not None
        assert asked.actor_user_id == community.id
        assert str(asked.actor_pat_id) == ids(named)[1]
