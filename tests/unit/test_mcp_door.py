"""The door: who gets in, what a refusal says, and what it does not say.

A surface is a second way into the corpus, so the questions here are the ones an
auditor would ask. Is an unauthenticated call refused before anything runs, does
a refusal say only what it should, and can a probe still tell whether the process
is alive without a credential.
"""

from __future__ import annotations

from pathlib import Path

import anyio
import httpx2
import pytest
from mcp.server.auth.provider import AccessToken

from dpolens_mcp.api import Api
from dpolens_mcp.credential import Credential, MissingCredential
from dpolens_mcp.identity import Introspecting
from dpolens_mcp.main import asgi
from dpolens_mcp.settings import Settings
from dpolens_stub import (
    DEVELOPER,
    PAT_ID,
    SURFACE,
    USER_ID,
    Stub,
    messages,
    recorded,
)

pytestmark = pytest.mark.anyio

ANYTHING = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def post(client: httpx2.AsyncClient, **headers: str) -> httpx2.Response:
    return await client.post("/mcp", json=ANYTHING, headers={**MCP_HEADERS, **headers})


class TestWhoGetsIn:
    async def test_a_call_with_no_credential_is_refused(
        self, over_http: httpx2.AsyncClient
    ) -> None:
        answer = await post(over_http)

        assert answer.status_code == 401

    async def test_nothing_reaches_the_instance_on_the_way_to_that_refusal(
        self, over_http: httpx2.AsyncClient, stub: Stub
    ) -> None:
        """Refused at the door means refused before a tool, and before any work."""
        await post(over_http)

        assert stub.seen == []

    async def test_the_refusal_points_at_no_authorization_server(
        self, over_http: httpx2.AsyncClient
    ) -> None:
        """There is no authorization server, so the refusal does not send anybody looking.

        DPOLens tokens are made on the instance's own command line. A refusal
        that advertised a login would send a client off to discover something
        that does not exist, and the real problem (a token that cannot be used)
        would never be read.
        """
        answer = await post(over_http)

        challenge = answer.headers["WWW-Authenticate"]
        assert challenge.startswith("Bearer ")
        assert "resource_metadata" not in challenge

    async def test_there_is_no_protected_resource_document_to_find(
        self, over_http: httpx2.AsyncClient
    ) -> None:
        answer = await over_http.get("/.well-known/oauth-protected-resource/mcp")

        assert answer.status_code == 404

    async def test_a_token_the_instance_will_not_vouch_for_is_refused(
        self, over_http: httpx2.AsyncClient, stub: Stub
    ) -> None:
        """Revoked, expired, unknown, or owned by somebody who left: one answer."""
        stub.active = False

        answer = await post(over_http, Authorization=f"Bearer {DEVELOPER}")

        assert answer.status_code == 401
        assert stub.calls("/v1/tokens/introspect") != []

    async def test_a_credential_without_the_bearer_scheme_is_refused(
        self, over_http: httpx2.AsyncClient, stub: Stub
    ) -> None:
        answer = await post(over_http, Authorization=DEVELOPER)

        assert answer.status_code == 401
        assert stub.seen == []

    async def test_an_instance_that_cannot_be_reached_refuses_rather_than_guesses(
        self, over_http: httpx2.AsyncClient, stub: Stub
    ) -> None:
        """A caller cannot be let in on the strength of an answer nobody gave.

        It is the one refusal that is not about the caller, so the reason goes to
        the log, where the person who can fix it will look.
        """
        stub.unreachable = {"/v1/tokens/introspect"}

        with recorded("dpolens_mcp.identity") as kept:
            answer = await post(over_http, Authorization=f"Bearer {DEVELOPER}")

        assert answer.status_code == 401
        assert "could not check a caller's token" in messages(kept)
        assert [record.levelname for record in kept] == ["ERROR"]

    async def test_a_token_the_instance_vouches_for_gets_in(
        self, over_http: httpx2.AsyncClient
    ) -> None:
        answer = await post(over_http, Authorization=f"Bearer {DEVELOPER}")

        assert answer.status_code == 200


class TestWhatTheVerifiedCallerCarries:
    async def test_it_carries_the_tokens_id_and_never_the_token(
        self, stub: Stub, surface_file: Path
    ) -> None:
        """A value that is not the secret cannot be passed upstream by accident."""
        api = Api(
            base_url="http://api.invalid",
            credential=Credential(surface_file),
            timeout=5,
            transport=stub.transport,
        )

        verified = await Introspecting(api).verify_token(DEVELOPER)
        await api.aclose()

        assert isinstance(verified, AccessToken)
        assert verified.token == PAT_ID
        assert verified.token != DEVELOPER
        assert verified.subject == USER_ID
        assert verified.client_id == PAT_ID
        assert verified.scopes == ["documents.read"]

    async def test_an_expiry_the_instance_gave_is_carried_in_seconds(
        self, stub: Stub, surface_file: Path
    ) -> None:
        stub.expires_at = "2030-01-01T00:00:00+00:00"
        api = Api(
            base_url="http://api.invalid",
            credential=Credential(surface_file),
            timeout=5,
            transport=stub.transport,
        )

        verified = await Introspecting(api).verify_token(DEVELOPER)
        await api.aclose()

        assert verified is not None
        assert verified.expires_at == 1893456000

    async def test_an_expiry_it_cannot_read_does_not_refuse_the_token(
        self, stub: Stub, surface_file: Path
    ) -> None:
        """Expiry is enforced where it is stored, so a date this cannot parse is not fatal."""
        stub.expires_at = "whenever"
        api = Api(
            base_url="http://api.invalid",
            credential=Credential(surface_file),
            timeout=5,
            transport=stub.transport,
        )

        with recorded("dpolens_mcp.identity") as kept:
            verified = await Introspecting(api).verify_token(DEVELOPER)
        await api.aclose()

        assert verified is not None
        assert verified.expires_at is None
        assert "could not read an expiry" in messages(kept)

    async def test_the_credential_it_presents_is_the_surface_credential(
        self, stub: Stub, surface_file: Path
    ) -> None:
        api = Api(
            base_url="http://api.invalid",
            credential=Credential(surface_file),
            timeout=5,
            transport=stub.transport,
        )

        await Introspecting(api).verify_token(DEVELOPER)
        await api.aclose()

        asked = stub.calls("/v1/tokens/introspect")[0]
        assert asked.headers["Authorization"] == f"Bearer {SURFACE}"


class TestTheProbe:
    async def test_it_answers_without_a_credential(self, over_http: httpx2.AsyncClient) -> None:
        """A health check that needs a credential is a health check nobody runs."""
        answer = await over_http.get("/live")

        assert answer.status_code == 200
        assert answer.json() == {"status": "alive"}

    async def test_it_touches_nothing_outside_the_process(
        self, over_http: httpx2.AsyncClient, stub: Stub
    ) -> None:
        """Liveness that reaches the API restarts this server whenever the API blinks."""
        await over_http.get("/live")

        assert stub.seen == []


class TestWhichNamesItAnswersTo:
    async def test_a_name_it_was_not_given_is_refused(self, over_http: httpx2.AsyncClient) -> None:
        """What keeps a page in a browser from reaching a server on a private network."""
        answer = await post(
            over_http, Authorization=f"Bearer {DEVELOPER}", Host="dpolens.example.com"
        )

        assert answer.status_code == 421

    async def test_a_name_it_was_given_is_answered(self, settings: Settings, stub: Stub) -> None:
        named = settings.model_copy(update={"allowed_hosts": ["dpolens.example.com:8765"]})
        api = Api(
            base_url=named.api,
            credential=Credential(named.surface_token_file),
            timeout=5,
            transport=stub.transport,
        )
        app = asgi(named, api)

        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app), base_url="http://dpolens.example.com:8765"
            ) as client,
        ):
            answer = await post(client, Authorization=f"Bearer {DEVELOPER}")

        assert answer.status_code == 200

    async def test_loopback_is_what_it_answers_to_until_a_name_is_given(
        self, settings: Settings
    ) -> None:
        assert settings.allowed_hosts == []
        assert settings.hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*"]


class TestStartingWithoutACredential:
    async def test_it_refuses_to_start_rather_than_serve_calls_it_cannot_make(
        self, tmp_path: Path, stub: Stub
    ) -> None:
        """Nothing is served until there is a credential to serve with."""
        missing = tmp_path / "never-written"
        settings = Settings(
            api_url="http://api.invalid",  # type: ignore[arg-type]
            surface_token_file=missing,
            credential_wait_seconds=0.2,
        )
        api = Api(
            base_url=settings.api,
            credential=Credential(missing),
            timeout=5,
            transport=stub.transport,
        )
        app = asgi(settings, api)

        with pytest.raises(MissingCredential, match="no credential at"):
            async with app.router.lifespan_context(app):
                pass  # pragma: no cover

    async def test_it_waits_for_the_file_the_instance_is_about_to_write(
        self, tmp_path: Path, stub: Stub
    ) -> None:
        """On a first run the API writes it while this server is already starting."""
        coming = tmp_path / "written-late"
        credential = Credential(coming)

        async def write_it_shortly() -> None:
            await anyio.sleep(0.1)
            coming.write_text(SURFACE, encoding="utf-8")

        async with anyio.create_task_group() as work:
            work.start_soon(write_it_shortly)
            held = await credential.wait(timeout=2, interval=0.05)

        assert held == SURFACE


class TestWhatThisServerAnswersAt:
    async def test_the_endpoint_is_mcp(self, over_http: httpx2.AsyncClient) -> None:
        """The URL a developer puts in their editor, so it is pinned by a test."""
        assert (await post(over_http, Authorization=f"Bearer {DEVELOPER}")).status_code == 200
        assert (await over_http.post("/", json=ANYTHING, headers=MCP_HEADERS)).status_code == 404

    async def test_an_answer_is_one_json_body(self, over_http: httpx2.AsyncClient) -> None:
        """Nothing here streams, and a plain body is what every proxy handles."""
        answer = await post(over_http, Authorization=f"Bearer {DEVELOPER}")

        assert answer.headers["content-type"].startswith("application/json")
        assert "tools" in answer.json()["result"]
