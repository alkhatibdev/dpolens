"""What every handler is given: a session, a caller, and a permission check.

Authentication and permission checks live here rather than in the engine, so a
route reads as one engine call with its guard stated above it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request

from dpolens.api import problems
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.tokens import (
    Authenticated,
    DelegationRefused,
    TokenRejected,
    UnknownToken,
    authenticate,
    authenticate_delegated,
    touch,
)
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.logs.governance import PAT_REJECTED, Actor, record
from dpolens.engine.session import EngineSession, session_from
from dpolens.settings import Settings

ON_BEHALF_OF_USER = "DPOLens-On-Behalf-Of-User"
ON_BEHALF_OF_TOKEN = "DPOLens-On-Behalf-Of-Token"
"""No `X-` prefix: RFC 6648 deprecated it for new headers.

`X-Request-Id` keeps its prefix because proxies and clients already emit it, and
interoperability wins for a header that is already everywhere.
"""


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def session(request: Request) -> Iterator[EngineSession]:
    """One session per request, on the engine the process opened at startup."""
    with session_from(request.app.state.engine) as opened:
        yield opened


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise problems.unauthenticated(
            "send a personal access token as `Authorization: Bearer dpol_...`"
        )
    return presented.strip()


def _delegated(
    request: Request, opened: EngineSession, surface: Authenticated
) -> Authenticated | None:
    """Honour an on-behalf-of assertion, or refuse it, or find none to honour."""
    user = request.headers.get(ON_BEHALF_OF_USER)
    token = request.headers.get(ON_BEHALF_OF_TOKEN)
    if user is None and token is None:
        return None
    if not surface.token.trusted_surface:
        raise problems.delegation_not_permitted()
    if user is None or token is None:
        raise problems.invalid_request(
            f"an assertion needs both {ON_BEHALF_OF_USER} and {ON_BEHALF_OF_TOKEN}"
        )

    try:
        return authenticate_delegated(opened, user_id=uuid.UUID(user), pat_id=uuid.UUID(token))
    except ValueError as malformed:
        raise problems.invalid_request("the asserted ids are not uuids") from malformed
    except DelegationRefused as refused:
        raise problems.unauthenticated(str(refused)) from refused
    except TokenRejected as rejected:
        _record_rejection(request, rejected)
        raise problems.token_refused(rejected.reason) from rejected


def _record_rejection(request: Request, rejected: TokenRejected) -> None:
    """A token with an owner that may not be used is the leak signal worth keeping.

    In a session of its own, not the request's: the request is about to fail, and
    a failing request rolls back. The record of a credential being refused has to
    outlive the refusal or it is not a record of anything.

    An unknown token writes nothing here. It has no owner, so there is nobody for
    an entry to be about, and it belongs in telemetry alone.
    """
    with session_from(request.app.state.engine) as own:
        record(
            own,
            actor=Actor(pat_id=rejected.token.id, via="api"),
            action=PAT_REJECTED,
            target_type="personal_access_token",
            target_id=str(rejected.token.id),
            details={"reason": rejected.reason, "prefix": rejected.token.prefix},
        )


Opened = Annotated[EngineSession, Depends(session)]


def caller(request: Request, opened: Opened) -> Authenticated:
    """Who is calling, after the token, the delegation and the limit are settled."""
    presented = _bearer(request)
    try:
        surface = authenticate(opened, presented)
    except UnknownToken as unknown:
        raise problems.unauthenticated("that token is not valid here") from unknown
    except TokenRejected as rejected:
        _record_rejection(request, rejected)
        raise problems.token_refused(rejected.reason) from rejected

    acting = _delegated(request, opened, surface) or surface

    # The limit counts the developer's token, not the surface's: one runaway
    # loop should not throttle everybody sharing an MCP server.
    retry_after = request.app.state.limiter.consume(str(acting.token.id))
    if retry_after is not None:
        raise problems.too_many_requests(retry_after)

    touch(opened, acting.token)
    request.state.caller = acting
    return acting


Caller = Annotated[Authenticated, Depends(caller)]


def requires(permission: str) -> Callable[[Authenticated], Authenticated]:
    """A dependency that refuses a caller whose token does not carry `permission`.

    A route states its guard in its own signature, so reading the route tells you
    what it takes to call it.
    """

    def guard(who: Caller) -> Authenticated:
        if not who.may(permission):
            raise problems.permission_required(permission)
        return who

    return guard


def trusted_surface_only(who: Caller) -> Authenticated:
    """For the endpoints only a surface has any business calling."""
    if not who.token.trusted_surface:
        raise problems.delegation_not_permitted()
    return who


Surface = Annotated[Authenticated, Depends(trusted_surface_only)]
Reader = Annotated[Authenticated, Depends(requires(catalog.DOCUMENTS_READ))]


def embedder(request: Request) -> Embedder:
    """The one model this process loaded at startup, shared by every request."""
    loaded: Embedder = request.app.state.embedder
    return loaded


Embedding = Annotated[Embedder, Depends(embedder)]
