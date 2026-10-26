"""The MCP server: four tools, two prompts, and one door.

Each tool is one call to the HTTP API and one shape handed back. The API decides
what a caller may read, so nothing here checks a permission twice: a permission
enforced in two places is a permission that can disagree with itself.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from typing import Annotated, Any

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from dpolens_mcp import __version__
from dpolens_mcp.api import Api, Caller, Refused, Unreachable
from dpolens_mcp.community import Community, wait_for
from dpolens_mcp.identity import Introspecting, calling
from dpolens_mcp.instructions import (
    COMMUNITY_CHECK,
    COMMUNITY_LIST,
    COMMUNITY_TOUR,
    INSTRUCTIONS,
    LIST,
    POLICY_CHECK,
    POLICY_TOUR,
    SEARCH,
    community_instructions,
    community_search,
)
from dpolens_mcp.results import (
    Clause,
    ClauseInContext,
    Document,
    DocumentInDetail,
    Documents,
    Found,
    Match,
    OutlineEntry,
    formerly,
    where_now,
)
from dpolens_mcp.settings import Settings

logger = logging.getLogger(__name__)

MAX_QUERY = 1000
"""The longest question the API accepts, refused here so the call is not made."""

READING = ToolAnnotations(read_only_hint=True, open_world_hint=False)
"""Every tool reads, nothing writes, and the corpus is this instance's own."""

TOLD = (400, 403, 404, 409, 422, 429)
"""Refusals a caller can act on, which are the ones a model is told about.

Anything else, including a credential problem belonging to whoever runs the
instance, is raised instead: the model is told the call failed, and the detail
goes to the operator's log where somebody can act on it.
"""


def build(settings: Settings, api: Api) -> MCPServer:
    """One server over one client of the API, which is the only thing it talks to."""
    community = settings.community
    days = settings.query_log_retention_days
    answering_as: Community | None = None

    def identify() -> Caller:
        """Who a call is made for: the Community account on a community version."""
        if answering_as is not None:
            return answering_as.caller()
        return calling()

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[None]:
        # Nothing is served until there is a credential to serve with, so a
        # container reports itself starting rather than answering calls it
        # cannot complete.
        nonlocal answering_as
        await api.credential.wait(timeout=settings.credential_wait_seconds)
        logger.info("read a surface credential from %s", api.credential.path)
        if community:
            answering_as = await wait_for(
                settings.community_file, timeout=settings.credential_wait_seconds
            )
            logger.info(
                "answering everyone as the Community account in %s", settings.community_file
            )
        try:
            yield
        finally:
            await api.aclose()

    mcp = MCPServer(
        name="dpolens",
        title="DPOLens",
        version=__version__,
        instructions=community_instructions(days) if community else INSTRUCTIONS,
        # A community version asks nobody for a token, so it has nothing to check.
        token_verifier=None if community else Introspecting(api),
        auth=None
        if community
        else AuthSettings(
            # Where tokens come from, which for DPOLens is the instance's own
            # command line. No metadata document is served and no authorization
            # server exists, so leaving the resource unset keeps this server from
            # pointing a client at one: a refused token is reported as a refused
            # token rather than as a login to go and find.
            issuer_url=settings.api_url,
            resource_server_url=None,
            required_scopes=[],
            validate_token_resource=False,
        ),
        lifespan=lifespan,
    )

    @mcp.tool(
        title="Search the law" if community else "Search the policies and the law",
        description=community_search(days) if community else SEARCH,
        annotations=READING,
    )
    async def search_policies(
        query: Annotated[
            str,
            Field(description="The question, in words", min_length=1, max_length=MAX_QUERY),
        ],
        limit: Annotated[int, Field(description="How many clauses to return", ge=1, le=50)] = 10,
        lang: Annotated[
            str | None,
            Field(
                description=(
                    "The language of the question, en or ar. Leave it out to have it read "
                    "from the letters the question is written in"
                )
            ),
        ] = None,
        as_of: Annotated[
            date | None,
            Field(description="Read the documents as they stood on this date"),
        ] = None,
        include_explanatory: Annotated[
            bool,
            Field(
                description=("Include text that explains without obliging, such as a GDPR recital")
            ),
        ] = False,
        laws: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Only these of the laws this organisation has selected, by slug, such as "
                    "gdpr or uae-pdpl. Leave it out to search all of them"
                ),
                max_length=20,
            ),
        ] = None,
    ) -> Found:
        caller = identify()
        with _answering():
            answer = await api.search(
                caller=caller,
                query=query,
                limit=limit,
                lang=lang,
                as_of=as_of,
                include_explanatory=include_explanatory,
                laws=laws,
            )

        results = [_match(result) for result in answer["results"]]
        return Found(
            searched=_scope(answer["laws"], as_of, policies=not community), results=results
        )

    @mcp.tool(title="Read one clause", annotations=READING)
    async def get_clause(
        key: Annotated[
            str,
            Field(description="A canonical key, such as gdpr:art-17:para-1"),
        ],
        lang: Annotated[
            str, Field(description="Which language to prefer, as a two letter code")
        ] = "en",
        as_of: Annotated[
            date | None,
            Field(description="Read the clause as it stood on this date"),
        ] = None,
        whole_subtree: Annotated[
            bool,
            Field(
                description=(
                    "Also return this clause and everything beneath it in reading order, "
                    "which is what you want for a whole article"
                )
            ),
        ] = False,
    ) -> ClauseInContext:
        """Read one clause by its key, with where it sits and what sits beneath it.

        Use it when a search result points at another clause, or when you need the whole
        of an article rather than the part that matched. The call is recorded, with the
        key that was read rather than a question.
        """
        caller = identify()
        with _answering():
            answer = await api.clause(caller=caller, key=key, lang=lang, as_of=as_of)
            branch = (
                await api.subtree(caller=caller, key=key, lang=lang, as_of=as_of)
                if whole_subtree
                else []
            )

        breadcrumb = answer["breadcrumb"]
        beneath = [*breadcrumb, answer["clause"]]
        return ClauseInContext(
            clause=Clause.of(answer["clause"], breadcrumb),
            children=[Clause.of(child, beneath) for child in answer["children"]],
            cross_references=[reference["key"] for reference in answer["cross_references"]],
            subtree=[Clause.of(view) for view in branch],
            now=where_now(answer["now"]) if answer.get("now") else None,
            formerly=(
                formerly(answer["clause"]["key"], answer["formerly"])
                if answer.get("formerly")
                else None
            ),
        )

    @mcp.tool(
        title="List what can be cited",
        description=COMMUNITY_LIST if community else LIST,
        annotations=READING,
    )
    async def list_documents(
        limit: Annotated[int, Field(description="How many to return", ge=1, le=100)] = 50,
        offset: Annotated[int, Field(description="Skip this many first", ge=0)] = 0,
        as_of: Annotated[
            date | None,
            Field(description="List the documents in force on this date"),
        ] = None,
    ) -> Documents:
        caller = identify()
        with _answering():
            answer = await api.documents(caller=caller, limit=limit, offset=offset, as_of=as_of)

        return Documents(
            documents=[Document.of(summary) for summary in answer["documents"]],
            total=answer["total"],
        )

    @mcp.tool(title="Read one document's outline", annotations=READING)
    async def get_document(
        slug: Annotated[str, Field(description="The document's slug, such as gdpr")],
        as_of: Annotated[
            date | None,
            Field(description="Read the document as it stood on this date"),
        ] = None,
    ) -> DocumentInDetail:
        """Read one document and its top level structure, without the text.

        The outline is where to find a clause key when you know roughly where to look.
        Read the words with get_clause. The call is recorded.
        """
        caller = identify()
        with _answering():
            answer = await api.document(caller=caller, slug=slug, as_of=as_of)

        return DocumentInDetail(
            document=Document.of(answer["document"]),
            outline=[
                OutlineEntry(
                    key=entry["key"],
                    label=entry["label"],
                    heading=entry["heading"],
                    obliges=entry["is_normative"],
                    children=entry["children"],
                )
                for entry in answer["outline"]
            ],
        )

    @mcp.prompt(
        title="Check this change against the law"
        if community
        else "Check this change against the policies"
    )
    def policy_check(
        focus: Annotated[
            str, Field(description="A file or area to look at, if you want to narrow it")
        ] = "",
    ) -> str:
        """Review the change you are working on against the policies and the law."""
        check = COMMUNITY_CHECK if community else POLICY_CHECK
        if focus.strip():
            return f"{check}\n\nStart with: {focus.strip()}"
        return check

    @mcp.prompt(title="Show me what this instance can do")
    def policy_tour() -> str:
        """Demonstrate this DPOLens instance with a few real searches."""
        return COMMUNITY_TOUR if community else POLICY_TOUR

    @mcp.custom_route("/live", methods=["GET"])  # type: ignore[untyped-decorator]
    async def live(request: Request) -> Response:
        """Say the process is running, touching nothing outside it."""
        return JSONResponse({"status": "alive"})

    return mcp


@contextmanager
def _answering() -> Iterator[None]:
    """Turn a refusal from the API into something a caller can act on.

    A refusal the caller can do something about reaches the model. Anything else
    is raised: the model is told the call failed, and the detail stays in the
    log, where the person who can fix it will look.
    """
    try:
        yield
    except Refused as refused:
        if refused.status in TOLD:
            raise _told(refused) from refused
        logger.error("the API refused a call: %s %s", refused.status, refused)
        raise RuntimeError(f"the DPOLens API refused this call ({refused.status})") from refused
    except Unreachable as unreachable:
        logger.error("%s", unreachable)
        raise RuntimeError(str(unreachable)) from unreachable


def _told(refused: Refused) -> ToolError:
    """The one error a model is meant to read, with what to do about it."""
    said = str(refused) or refused.title
    if refused.status == 429 and refused.retry_after is not None:
        return ToolError(f"{said}. Wait {refused.retry_after} seconds and ask again.")
    # A law outside the selection already says who can add it; a permission does not.
    if refused.status == 403 and refused.type != "/problems/law-not-selected":
        return ToolError(f"{said}. Whoever administers this DPOLens instance can grant it.")
    if refused.status == 404:
        return ToolError(f"{said}. list_documents shows what this instance can cite.")
    return ToolError(said)


def _scope(laws: list[str], as_of: date | None, *, policies: bool) -> str:
    """What a search covered. A community version holds no organisation's policies."""
    when = f"as they stood on {as_of.isoformat()}" if as_of else "as they stand today"
    searched = ", ".join(laws) or "no law"
    if policies:
        searched += ", and the organisation's own policies"
    return f"{searched}, {when}"


def _match(result: dict[str, Any]) -> Match:
    """One search result, flattened: a clause is easier to read than a clause in a box."""
    clause = Clause.of(result["clause"], result["breadcrumb"])
    return Match(
        **clause.model_dump(),
        score=result["score"],
        cross_references=[reference["key"] for reference in result["cross_references"]],
    )
