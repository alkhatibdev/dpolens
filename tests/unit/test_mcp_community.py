"""A community version: anyone is answered without a token, as the Community account,
told how questions are kept, and held to three limits.

Driven over the stub instance, as the other MCP tests are.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from dpolens_mcp.api import ON_BEHALF_OF_TOKEN, ON_BEHALF_OF_USER, Api
from dpolens_mcp.community import Allowance, NoCommunityAccount, wait_for
from dpolens_mcp.credential import Credential
from dpolens_mcp.main import asgi
from dpolens_mcp.settings import Settings
from dpolens_stub import HOST, Stub, structured

pytestmark = pytest.mark.anyio

COMMUNITY_USER = "33333333-3333-3333-3333-333333333333"
COMMUNITY_TOKEN = "44444444-4444-4444-4444-444444444444"
CLAUDE = "160.79.104.0/21"


def community(surface_file: Path, tmp_path: Path, **limits: int) -> Settings:
    named = tmp_path / "community"
    named.write_text(json.dumps({"user": COMMUNITY_USER, "token": COMMUNITY_TOKEN}))
    return Settings.model_validate(
        {
            "api_url": "http://api.invalid",
            "surface_token_file": surface_file,
            "credential_wait_seconds": 1,
            "community": True,
            "community_file": named,
            "path": "/",
            "client_address_header": "CF-Connecting-IP",
            "shared_ranges": [CLAUDE],
            "DPOLENS_QUERY_LOG_RETENTION_DAYS": 30,
            **limits,
        }
    )


@asynccontextmanager
async def started(settings: Settings, stub: Stub) -> AsyncIterator[Starlette]:
    api = Api(
        base_url=settings.api,
        credential=Credential(settings.surface_token_file),
        timeout=5,
        transport=stub.transport,
    )
    app = asgi(settings, api)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def open_door(surface_file: Path, tmp_path: Path, stub: Stub) -> AsyncIterator[Starlette]:
    """A community version with its usual limits, which one conversation never reaches."""
    async with started(community(surface_file, tmp_path), stub) as app:
        yield app


@pytest.fixture
async def tight(surface_file: Path, tmp_path: Path, stub: Stub) -> AsyncIterator[Starlette]:
    """A community version whose limits a handful of calls reach."""
    limits = {"per_address_per_minute": 2, "per_range_per_minute": 3, "overall_per_minute": 5}
    async with started(community(surface_file, tmp_path, **limits), stub) as app:
        yield app


@pytest.fixture
async def anyone(open_door: Starlette) -> AsyncIterator[Client]:
    """An MCP client with no token at all, at the version's own address."""
    async with (
        httpx2.AsyncClient(transport=httpx2.ASGITransport(open_door), base_url=HOST) as http,
        Client(
            streamable_http_client(f"{HOST}/", http_client=http), raise_exceptions=True
        ) as client,
    ):
        yield client


async def test_anyone_is_answered_without_a_token_as_the_community_account(
    anyone: Client, stub: Stub
) -> None:
    result = await anyone.call_tool("search_policies", {"query": "retention"})

    assert result.is_error is False
    assert structured(result)["results"]
    asked = stub.calls("/v1/search")[0]
    assert asked.headers[ON_BEHALF_OF_USER] == COMMUNITY_USER
    assert asked.headers[ON_BEHALF_OF_TOKEN] == COMMUNITY_TOKEN
    assert stub.calls("/v1/tokens/introspect") == []


async def test_the_assistant_is_told_what_it_searches_and_how_questions_are_kept(
    anyone: Client,
) -> None:
    listed = await anyone.list_tools()
    tour = await anyone.get_prompt("policy_tour")

    search = next(tool for tool in listed.tools if tool.name == "search_policies")
    described = " ".join((search.description or "").split())
    assert "the privacy law this community version holds" in described
    assert "kept 30 days, with nothing about who asked" in described
    assert "organisation's privacy policies" not in described
    told = " ".join(str(message.content) for message in tour.messages)
    assert "community version" in told
    assert "github.com/alkhatibdev/dpolens" in told


async def test_the_server_says_it_on_connect(open_door: Starlette) -> None:
    async with (
        httpx2.AsyncClient(transport=httpx2.ASGITransport(open_door), base_url=HOST) as http,
        Client(streamable_http_client(f"{HOST}/", http_client=http)) as client,
    ):
        instructions = " ".join((client.instructions or "").split())

    assert instructions.startswith("This is the DPOLens community version.")
    assert "Questions asked here are kept 30 days, with nothing about who asked" in instructions


def mcp_post(http: httpx2.AsyncClient, address: str) -> object:
    return http.post("/", json={}, headers={"CF-Connecting-IP": address})


async def test_one_address_is_held_to_its_own_allowance(tight: Starlette) -> None:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(tight), base_url=HOST) as http:
        answers = [await mcp_post(http, "203.0.113.7") for _ in range(3)]  # type: ignore[misc]
        another = await mcp_post(http, "203.0.113.8")  # type: ignore[misc]

    assert [answer.status_code == 429 for answer in answers] == [False, False, True]
    assert int(answers[2].headers["Retry-After"]) >= 1
    assert another.status_code != 429


async def test_a_platform_s_range_shares_one_larger_allowance(tight: Starlette) -> None:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(tight), base_url=HOST) as http:
        answers = [
            await mcp_post(http, f"160.79.104.{host}")  # type: ignore[misc]
            for host in range(1, 5)
        ]

    # Each address alone would have been allowed; together they are one platform.
    assert [answer.status_code == 429 for answer in answers] == [False, False, False, True]


async def test_everybody_together_is_held_to_the_overall_allowance(tight: Starlette) -> None:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(tight), base_url=HOST) as http:
        answers = [
            await mcp_post(http, f"198.51.100.{host}")  # type: ignore[misc]
            for host in range(1, 7)
        ]

    assert [answer.status_code == 429 for answer in answers] == [False] * 5 + [True]


async def test_being_alive_is_never_counted(tight: Starlette) -> None:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(tight), base_url=HOST) as http:
        answers = [
            await http.get("/live", headers={"CF-Connecting-IP": "203.0.113.9"}) for _ in range(10)
        ]

    assert {answer.status_code for answer in answers} == {200}


def test_an_allowance_fills_again_with_time() -> None:
    allowance = Allowance(per_minute=60)

    assert [allowance.take("one", now=0.0) for _ in range(60)] == [None] * 60
    assert allowance.take("one", now=0.0) == 1
    assert allowance.take("one", now=1.0) is None


async def test_without_the_account_file_the_server_does_not_start(tmp_path: Path) -> None:
    with pytest.raises(NoCommunityAccount, match="DPOLENS_COMMUNITY"):
        await wait_for(tmp_path / "missing", timeout=0)
