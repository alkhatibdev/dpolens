"""Introspection: what a surface asks before acting for somebody.

A surface never receives the caller's token as its own credential, and it never
passes one upstream. It presents its own, asks about the caller's, and then makes
the real request with an on-behalf-of assertion the API checks.

The answer is not cached anywhere. Introspection is a loopback call next to a
search that costs far more, so a cache would save a millisecond and buy a window
in which a revoked token still works.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from dpolens.api.dependencies import Opened, Surface
from dpolens.engine.auth.tokens import TokenRejected, UnknownToken, authenticate

router = APIRouter(prefix="/v1/tokens", tags=["tokens"])


class IntrospectionRequest(BaseModel):
    token: str = Field(description="The token presented by the caller being asked about")


class Introspection(BaseModel):
    """Who a token belongs to, and what it may do right now.

    `active` is false for anything that cannot be used, whether it is unknown,
    revoked, expired or owned by somebody who has left. A surface only needs to
    know that it cannot act; the API decides what it may do on the call itself.
    """

    active: bool
    user_id: str | None = None
    email: str | None = None
    pat_id: str | None = None
    permissions: list[str] = Field(default_factory=list)
    expires_at: str | None = None


@router.post("/introspect", summary="Ask about a token a caller presented")
def introspect(body: IntrospectionRequest, surface: Surface, opened: Opened) -> Introspection:
    assert surface  # the dependency is the authorisation; this keeps it in the signature
    try:
        who = authenticate(opened, body.token)
    except UnknownToken, TokenRejected:
        return Introspection(active=False)

    return Introspection(
        active=True,
        user_id=str(who.user.id),
        email=who.user.email,
        pat_id=str(who.token.id),
        permissions=sorted(who.permissions),
        expires_at=who.token.expires_at.isoformat() if who.token.expires_at else None,
    )
