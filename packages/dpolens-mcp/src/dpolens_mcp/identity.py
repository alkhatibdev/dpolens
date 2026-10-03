"""Who is calling, and how this server finds out.

A caller presents their own personal access token. This server checks it with
the API, then makes the real request with its own credential and an assertion
naming the caller, which the API checks rather than believes. The caller's token
is never sent on: the protocol forbids it, and the token is not this server's to
spend.

Checking happens at the door, so a request with no usable token is refused
before a tool runs. Nothing about it is cached: revoking a token takes effect on
the next call.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.mcpserver.exceptions import ToolError

from dpolens_mcp.api import Api, Caller, Refused, Unreachable
from dpolens_mcp.credential import MissingCredential

logger = logging.getLogger(__name__)


class Introspecting(TokenVerifier):
    """Checks a presented token with the API, and keeps the secret out of the result.

    The verified token this returns carries the token's id where the raw
    credential would normally sit. A value that is not the secret cannot be
    passed upstream by accident, which is the rule this server has to keep.
    """

    def __init__(self, api: Api) -> None:
        self._api = api

    async def verify_token(self, token: str) -> AccessToken | None:
        # One id for the pair of calls: the question asked here and the call it
        # leads to appear in the API's logs under the same request id.
        request_id = str(uuid.uuid4())
        try:
            who = await self._api.introspect(token, request_id=request_id)
        except (Refused, Unreachable, MissingCredential) as failed:
            # A failure here is about this server's own credential or about the
            # instance being unreachable, not about the caller. The caller is
            # told the request was not authenticated, because that is all this
            # server can honestly say, and the reason goes to the operator.
            logger.error("could not check a caller's token: %s", failed)
            return None

        if who is None:
            return None

        return AccessToken(
            token=who.pat_id,
            client_id=who.pat_id,
            scopes=list(who.permissions),
            subject=who.user_id,
            expires_at=_seconds(who.expires_at),
            claims={"request_id": request_id},
        )


def calling() -> Caller:
    """Who the current call is for, from the token the door already checked."""
    verified = get_access_token()
    if verified is None or verified.subject is None:
        raise ToolError(
            "this call carried no checked credential. Send a DPOLens personal access token "
            "as `Authorization: Bearer dpol_...`."
        )
    claims = verified.claims or {}
    return Caller(
        user_id=verified.subject,
        pat_id=verified.client_id,
        request_id=str(claims.get("request_id") or uuid.uuid4()),
    )


def _seconds(expires_at: str | None) -> int | None:
    """An expiry as whole seconds, which is what a verified token carries."""
    if expires_at is None:
        return None
    try:
        return int(datetime.fromisoformat(expires_at).timestamp())
    except ValueError:
        # A timestamp this server cannot read is not a reason to refuse a token
        # the API has just said is usable. The API is where expiry is enforced.
        logger.warning("could not read an expiry from the API: %r", expires_at)
        return None
