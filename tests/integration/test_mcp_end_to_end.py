"""The MCP server over the real API, with a real token and a real corpus.

The unit tests put a stub where the instance is, which proves the shapes and the
refusals. This proves the part a stub cannot: that a credential minted on the
command line is accepted at the door, that acting on somebody's behalf is
accepted by the API as well as sent by the surface, and that the query log ends
up naming the developer rather than the server they went through.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.surface import ensure_surface
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user
from dpolens.engine.embedding import DEFAULT_MODEL, get_model
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.index import build_index
from dpolens.engine.logs.governance import Actor
from dpolens.engine.logs.models import QueryLogEntry
from dpolens.engine.packs.load import load_pack
from dpolens.engine.session import session_from
from dpolens.settings import Settings as EngineSettings
from dpolens_mcp.api import Api
from dpolens_mcp.credential import Credential
from dpolens_mcp.main import asgi
from dpolens_mcp.settings import Settings
from dpolens_stub import HOST

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
TESTLAW = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def corpus(committed_owner_url: str) -> Iterator[Engine]:
    engine = create_engine(committed_owner_url)
    with session_from(engine) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, TESTLAW)
    with Embedder(get_model(DEFAULT_MODEL)) as embedder, session_from(engine) as opened:
        build_index(opened, embedder)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def api_app(committed_database_url: str, corpus: Engine) -> FastAPI:
    return create_app(EngineSettings.model_validate({"database_url": committed_database_url}))


@pytest.fixture(scope="module")
async def running_api(api_app: FastAPI) -> AsyncIterator[FastAPI]:
    """The API with its startup done: one engine, one embedding model, one catalog.

    Entered once for the module, because loading the model is the slow part and
    an instance loads it once too.
    """
    async with api_app.router.lifespan_context(api_app):
        yield api_app


@pytest.fixture(scope="module")
def surface(corpus: Engine, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The credential the instance provisions for a surface, on disk as it would be."""
    path = tmp_path_factory.mktemp("surface") / "surface-token"
    with session_from(corpus) as opened:
        ensure_surface(opened, path=path, actor=ACTOR, email="mcp-e2e@surface.invalid")
    return path


@pytest.fixture
def developer(corpus: Engine, unique: str) -> dict[str, str]:
    """A developer with a token, as `dpolens user create` and `token create` leave it."""
    email = f"mcp-dev-{unique}@example.com"
    with session_from(corpus) as opened:
        user = create_user(
            opened,
            email=email,
            display_name="A developer",
            actor=ACTOR,
            roles=(catalog.DEVELOPER,),
        )
        opened.flush()
        row, token = mint(
            opened,
            email=email,
            name="laptop",
            permissions=(catalog.DOCUMENTS_READ,),
            actor=ACTOR,
        )
        return {"token": token, "user_id": str(user.id), "pat_id": str(row.id)}


@pytest.fixture
async def connected(
    running_api: FastAPI, surface: Path, developer: dict[str, str]
) -> AsyncIterator[Client]:
    """A client of the MCP server, which is a client of the API, which is the engine."""
    settings = Settings(
        api_url="http://api.invalid",  # type: ignore[arg-type]
        surface_token_file=surface,
        credential_wait_seconds=5,
    )
    api = Api(
        base_url=settings.api,
        credential=Credential(surface),
        timeout=30,
        transport=httpx2.ASGITransport(running_api),
    )
    app = asgi(settings, api)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app),
            base_url=HOST,
            headers={"Authorization": f"Bearer {developer['token']}"},
        ) as http,
        Client(
            streamable_http_client(f"{HOST}/mcp", http_client=http), raise_exceptions=True
        ) as client,
    ):
        yield client


def structured(result: Any) -> dict[str, Any]:
    answer: dict[str, Any] = result.structured_content or {}
    return answer


def latest(session: Session) -> QueryLogEntry:
    session.expire_all()
    return session.scalars(
        select(QueryLogEntry).order_by(QueryLogEntry.created_at.desc()).limit(1)
    ).one()


class TestAQuestionFromAnAssistant:
    async def test_it_comes_back_with_a_clause_and_a_citation(self, connected: Client) -> None:
        result = await connected.call_tool("search_policies", {"query": "personal data"})

        found = structured(result)["results"]
        assert found
        assert found[0]["key"].startswith("testlaw:")
        assert found[0]["text"]
        assert found[0]["citation"].endswith(f"in force since {found[0]['in_force_since']}")

    async def test_a_key_from_a_search_can_be_read_back(self, connected: Client) -> None:
        """The loop an assistant actually walks: search, then read the clause."""
        found = await connected.call_tool("search_policies", {"query": "personal data"})
        key = structured(found)["results"][0]["key"]

        clause = await connected.call_tool("get_clause", {"key": key})

        assert structured(clause)["clause"]["key"] == key

    async def test_the_documents_it_can_cite_are_listed(self, connected: Client) -> None:
        result = await connected.call_tool("list_documents", {})

        slugs = [document["slug"] for document in structured(result)["documents"]]
        assert "testlaw" in slugs

    async def test_an_outline_comes_back_for_a_document(self, connected: Client) -> None:
        result = await connected.call_tool("get_document", {"slug": "testlaw"})

        assert structured(result)["document"]["slug"] == "testlaw"
        assert structured(result)["outline"]


class TestWhoTheInstanceThinksIsAsking:
    async def test_the_query_log_names_the_developer_and_not_the_surface(
        self, connected: Client, developer: dict[str, str], corpus: Engine
    ) -> None:
        """The whole point of acting on somebody's behalf rather than as somebody."""
        await connected.call_tool("search_policies", {"query": "erasure of personal data"})

        with session_from(corpus) as opened:
            entry = latest(opened)
            assert entry.operation == "search"
            assert str(entry.actor_user_id) == developer["user_id"]
            assert str(entry.actor_pat_id) == developer["pat_id"]

    async def test_the_row_says_the_question_came_through_a_surface(
        self, connected: Client, corpus: Engine
    ) -> None:
        await connected.call_tool("search_policies", {"query": "retention of records"})

        with session_from(corpus) as opened:
            assert latest(opened).surface == "mcp"

    async def test_the_question_is_stored_redacted(self, connected: Client, corpus: Engine) -> None:
        """Redaction is the API's, and a surface does not get to skip it."""
        await connected.call_tool(
            "search_policies", {"query": "can we email hamad@example.com about erasure"}
        )

        with session_from(corpus) as opened:
            entry = latest(opened)
            assert "hamad@example.com" not in entry.query_redacted
            assert "[redacted:email]" in entry.query_redacted


class TestWhatTheDoorRefuses:
    async def test_a_token_that_was_never_minted_here_is_refused(
        self, running_api: FastAPI, surface: Path
    ) -> None:
        settings = Settings(
            api_url="http://api.invalid",  # type: ignore[arg-type]
            surface_token_file=surface,
            credential_wait_seconds=5,
        )
        api = Api(
            base_url=settings.api,
            credential=Credential(surface),
            timeout=30,
            transport=httpx2.ASGITransport(running_api),
        )
        app = asgi(settings, api)

        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(transport=httpx2.ASGITransport(app), base_url=HOST) as http,
        ):
            answer = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={
                    "Authorization": "Bearer dpol_neverminted",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )

        assert answer.status_code == 401

    async def test_a_developer_without_the_permission_is_told_which_one(
        self, running_api: FastAPI, surface: Path, corpus: Engine, unique: str
    ) -> None:
        """A token that carries nothing is refused by the API, not by the surface."""
        email = f"mcp-nothing-{unique}@example.com"
        with session_from(corpus) as opened:
            create_user(
                opened,
                email=email,
                display_name="No permissions",
                actor=ACTOR,
                roles=(catalog.DEVELOPER,),
            )
            opened.flush()
            _, token = mint(opened, email=email, name="laptop", permissions=(), actor=ACTOR)

        settings = Settings(
            api_url="http://api.invalid",  # type: ignore[arg-type]
            surface_token_file=surface,
            credential_wait_seconds=5,
        )
        api = Api(
            base_url=settings.api,
            credential=Credential(surface),
            timeout=30,
            transport=httpx2.ASGITransport(running_api),
        )
        app = asgi(settings, api)

        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app),
                base_url=HOST,
                headers={"Authorization": f"Bearer {token}"},
            ) as http,
            Client(
                streamable_http_client(f"{HOST}/mcp", http_client=http), raise_exceptions=True
            ) as client,
        ):
            result = await client.call_tool("search_policies", {"query": "anything"})

        said = "\n".join(block.text for block in result.content if hasattr(block, "text"))
        assert result.is_error is True
        assert catalog.DOCUMENTS_READ in said
