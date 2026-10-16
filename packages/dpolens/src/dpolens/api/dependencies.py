"""What every handler is given: a session, a caller, and a permission check.

Authentication and permission checks live here rather than in the engine, so a
route reads as one engine call with its guard stated above it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request

from dpolens.api import problems
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.sessions import SessionEnded, UnknownSession, lifetimes_of, resolve
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

SESSION_COOKIE = "__Host-dpolens_session"
"""The `__Host-` prefix makes a browser refuse the cookie unless it is Secure, set
for the whole site and tied to this host alone, so no subdomain can plant or
read it."""

PLAIN_HTTP_SESSION_COOKIE = "dpolens_session"
"""The name when the browser is on plain HTTP, where the prefix cannot hold."""

ON_BEHALF_OF_USER = "DPOLens-On-Behalf-Of-User"
ON_BEHALF_OF_TOKEN = "DPOLens-On-Behalf-Of-Token"
"""No `X-` prefix: RFC 6648 deprecated it for new headers.

`X-Request-Id` keeps its prefix because proxies and clients already emit it, and
interoperability wins for a header that is already everywhere.
"""


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


Configured = Annotated[Settings, Depends(settings_of)]


def browser_uses_https(request: Request) -> bool:
    """Whether the page a request came from was served over HTTPS, read from `Origin`.

    The browser sets `Origin` and no page can change it, and it names the scheme
    the person actually used, whatever proxies sit between. A browser keeps a
    Secure cookie only over HTTPS (Safari not even on localhost), and on plain
    HTTP the flag protects nothing, so the cookie follows the scheme. A request
    without `Origin` is not a browser's, and gets the strict default.
    """
    origin = request.headers.get("Origin")
    return origin is None or urlsplit(origin).scheme == "https"


def session_cookie_name(secure: bool) -> str:
    return SESSION_COOKIE if secure else PLAIN_HTTP_SESSION_COOKIE


def presented_session(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE) or request.cookies.get(PLAIN_HTTP_SESSION_COOKIE)


def check_same_origin(request: Request) -> None:
    """A request made with the session cookie has to come from the dashboard's own pages.

    `SameSite=Strict` already keeps the cookie off a request another site starts.
    The browser's `Sec-Fetch-Site`, which no page can set, is checked as well, so a
    browser or a proxy that gets SameSite wrong still cannot be used against the
    API. A request without the header is not from a browser, and has no business
    with a browser's cookie.
    """
    if request.headers.get("Sec-Fetch-Site") != "same-origin":
        raise problems.cross_site_request()


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
    if surface.token is None or not surface.token.trusted_surface:
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


def _with_token(request: Request, opened: EngineSession) -> Authenticated:
    presented = _bearer(request)
    try:
        surface = authenticate(opened, presented)
    except UnknownToken as unknown:
        raise problems.unauthenticated("that token is not valid here") from unknown
    except TokenRejected as rejected:
        _record_rejection(request, rejected)
        raise problems.token_refused(rejected.reason) from rejected
    return _delegated(request, opened, surface) or surface


def _signed_in(request: Request, opened: EngineSession, secret: str) -> Authenticated:
    settings = settings_of(request)
    check_same_origin(request)
    try:
        row = resolve(opened, secret, lifetimes=lifetimes_of(settings))
    except UnknownSession as unknown:
        raise problems.session_ended("unknown") from unknown
    except SessionEnded as ended:
        raise problems.session_ended(ended.reason) from ended
    return Authenticated(
        token=None, user=row.user, permissions=row.user.effective_permissions(), session=row
    )


def caller(request: Request, opened: Opened) -> Authenticated:
    """Who is calling, after the credential, the delegation and the limit are settled.

    A token in the `Authorization` header wins over a cookie: a client that names
    a credential has said which one it means.
    """
    secret = presented_session(request)
    if secret and "Authorization" not in request.headers:
        acting = _signed_in(request, opened, secret)
    else:
        acting = _with_token(request, opened)

    # The limit counts the developer's token, not the surface's: one runaway
    # loop should not throttle everybody sharing an MCP server.
    retry_after = request.app.state.limiter.consume(acting.credential_id)
    if retry_after is not None:
        raise problems.too_many_requests(retry_after)

    if acting.token is not None:
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


def requires_any(*permissions: str) -> Callable[[Authenticated], Authenticated]:
    """Like `requires`, for a page more than one permission opens."""

    def guard(who: Caller) -> Authenticated:
        if not any(who.may(permission) for permission in permissions):
            raise problems.permission_required_any(permissions)
        return who

    return guard


def expected_revision(if_match: str | None, of: str) -> int | None:
    """The revision an `If-Match` names, or None when it names none to check. `of` says what
    the revision belongs to, for the refusal."""
    if if_match is None or if_match.strip() == "*":
        return None
    value = if_match.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise problems.invalid_request(f"If-Match carries the {of}'s revision, as its ETag gave it")
    return int(value)


def actor_of(who: Authenticated) -> Actor:
    """Who a governance entry names for this caller, and through which door."""
    return Actor(
        user_id=who.user.id,
        pat_id=who.token.id if who.token is not None else None,
        via="dashboard" if who.session is not None else "api",
    )


def trusted_surface_only(who: Caller) -> Authenticated:
    """For the endpoints only a surface has any business calling."""
    if who.token is None or not who.token.trusted_surface:
        raise problems.delegation_not_permitted()
    return who


Surface = Annotated[Authenticated, Depends(trusted_surface_only)]
Reader = Annotated[Authenticated, Depends(requires(catalog.DOCUMENTS_READ))]


def embedder(request: Request) -> Embedder:
    """The one model this process loaded at startup, shared by every request."""
    loaded: Embedder = request.app.state.embedder
    return loaded


Embedding = Annotated[Embedder, Depends(embedder)]


def was_delegated(request: Request) -> bool:
    """Whether a surface asked on somebody's behalf, which is what names it."""
    return ON_BEHALF_OF_USER in request.headers


Delegated = Annotated[bool, Depends(was_delegated)]
