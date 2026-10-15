"""Tokens: a person's own, everyone's for whoever manages people, and introspection.

A token is made from a dashboard session and never with another token, so a
leaked token cannot mint its own replacements. It can do only what its owner
can, at creation and on every request after. Anyone may see and revoke their own
tokens, even after losing the permission to make new ones, because cutting off a
credential must never wait for a permission.

Introspection is what a surface asks before acting for somebody. A surface never
receives the caller's token as its own credential, and it never passes one
upstream. It presents its own, asks about the caller's, and then makes the real
request with an on-behalf-of assertion the API checks. The answer is not cached
anywhere: introspection is a loopback call next to a search that costs far more,
so a cache would save a millisecond and buy a window in which a revoked token
still works.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from dpolens.api import problems
from dpolens.api.dependencies import Caller, Opened, Surface, actor_of
from dpolens.engine.auth import listing
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.models import PersonalAccessToken
from dpolens.engine.auth.roles import UnknownPermission
from dpolens.engine.auth.tokens import (
    OwnerCannotHoldTokens,
    PermissionsExceedOwner,
    TokenNotFound,
    TokenRejected,
    UnknownToken,
    authenticate,
    effective_permissions,
    get_token,
    mint,
    revoke_token,
    status_of,
)

router = APIRouter(
    prefix="/v1/tokens",
    tags=["tokens"],
    responses=problems.responses(401, 403, 429),
)


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
    if who.token is None:
        return Introspection(active=False)

    return Introspection(
        active=True,
        user_id=str(who.user.id),
        email=who.user.email,
        pat_id=str(who.token.id),
        permissions=sorted(who.permissions),
        expires_at=who.token.expires_at.isoformat() if who.token.expires_at else None,
    )


Kind = Literal["person", "service_account"]
TokenStatus = Literal["active", "revoked", "expired", "owner_inactive"]


class Owner(BaseModel):
    id: str
    display_name: str
    kind: Kind


class TokenDocument(BaseModel):
    """A token as its list shows it. The secret is never here, except once at creation."""

    id: str
    name: str
    prefix: str = Field(description="The first characters, to tell tokens apart")
    owner: Owner
    permissions: list[str] = Field(description="What it was given when it was made")
    effective_permissions: list[str] = Field(
        description="What it may do now: the above, narrowed by what its owner holds today"
    )
    trusted_surface: bool = Field(description="May say which person it is acting for")
    status: TokenStatus
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def of(cls, row: PersonalAccessToken) -> TokenDocument:
        status = status_of(row)
        return cls(
            id=str(row.id),
            name=row.name,
            prefix=row.prefix,
            owner=Owner(
                id=str(row.owner.id),
                display_name=row.owner.display_name,
                kind=cast(Kind, row.owner.kind),
            ),
            permissions=sorted(row.permissions),
            effective_permissions=sorted(effective_permissions(row, row.owner)),
            trusted_surface=row.trusted_surface,
            status=cast(TokenStatus, "owner_inactive" if status.startswith("owner") else status),
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )


class Tokens(BaseModel):
    tokens: list[TokenDocument]


class NewToken(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(min_length=1, max_length=len(catalog.PERMISSIONS))
    expires_at: datetime | None = Field(default=None, description="Left out, it does not expire")


class TokenMade(TokenDocument):
    secret: str = Field(description="The token itself, shown this once")


@router.get("", summary="List your tokens, or everyone's")
def list_tokens(
    who: Caller,
    opened: Opened,
    everyone: Annotated[bool, Query(description="Everyone's, which needs users.manage")] = False,
) -> Tokens:
    if everyone and not who.may(catalog.USERS_MANAGE):
        raise problems.permission_required(catalog.USERS_MANAGE)
    rows = listing.tokens(opened, owner=None if everyone else who.user)
    return Tokens(tokens=[TokenDocument.of(row) for row in rows])


@router.post(
    "",
    status_code=201,
    summary="Make a token for yourself",
    responses=problems.responses(400),
)
def make_token(body: NewToken, who: Caller, opened: Opened) -> TokenMade:
    if who.session is None:
        raise problems.session_required()
    if not who.may(catalog.TOKENS_CREATE):
        raise problems.permission_required(catalog.TOKENS_CREATE)
    if body.expires_at is not None and body.expires_at <= datetime.now(UTC):
        raise problems.invalid_request("expires_at has to be in the future")
    try:
        row, secret = mint(
            opened,
            email=who.user.email,
            name=body.name.strip(),
            permissions=body.permissions,
            actor=actor_of(who),
            expires_at=body.expires_at,
        )
    except UnknownPermission as unknown:
        raise problems.invalid_request(str(unknown)) from unknown
    except PermissionsExceedOwner as excess:
        missing = sorted(set(body.permissions) - who.user.effective_permissions())
        raise problems.permission_required(missing[0]) from excess
    except OwnerCannotHoldTokens as refused:
        raise problems.invalid_request(str(refused)) from refused
    return TokenMade(**TokenDocument.of(row).model_dump(), secret=secret)


@router.delete(
    "/{token_id}",
    status_code=204,
    summary="Revoke a token",
    response_class=Response,
    responses=problems.responses(404),
)
def revoke(token_id: uuid.UUID, who: Caller, opened: Opened) -> Response:
    try:
        row = get_token(opened, token_id)
    except TokenNotFound as missing:
        raise problems.not_found(str(missing)) from missing
    if row.user_id != who.user.id and not who.may(catalog.USERS_MANAGE):
        # Somebody else's token, to a caller who may not manage people: answered as
        # if it did not exist, so the route cannot be used to learn token ids.
        raise problems.not_found(f"no token with the id {token_id}")
    revoke_token(opened, row, actor=actor_of(who))
    return Response(status_code=204)
