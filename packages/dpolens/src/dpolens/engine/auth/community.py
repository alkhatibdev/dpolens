"""The account the community version answers everyone as.

The community version takes questions from anyone, with no token, so all of them
are asked as one service account, Community, whose token may read documents and
nothing else. The MCP server is told the account's id and its token's id, which it
names when it acts for a caller, as it does for a person. The token's secret is
never written down, because nothing ever presents it, and revoking the token closes
the community version.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import PersonalAccessToken, User
from dpolens.engine.auth.permissions import DOCUMENTS_READ
from dpolens.engine.auth.roles import create_role
from dpolens.engine.auth.surface import SurfaceOwnerIsAPerson, write_shared
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import RoleNotFound, UserNotFound, create_user, get_role, get_user
from dpolens.engine.logs.governance import Actor

COMMUNITY_EMAIL = "community@community.invalid"
"""`.invalid` resolves nowhere, so the account can never be mistaken for a person's."""

COMMUNITY_ROLE = "Community"
COMMUNITY_TOKEN = "community"


@dataclass(frozen=True)
class CommunityAccount:
    """What `ensure_community` set up, as plain values a command can print later."""

    user_id: uuid.UUID
    token_id: uuid.UUID
    token_prefix: str
    minted: bool


def ensure_community(session: Session, *, path: Path, actor: Actor) -> CommunityAccount:
    """Make sure the Community account, its role and a working token exist, and that
    `path` names them. Safe to run on every start: what works is left alone."""
    try:
        get_role(session, COMMUNITY_ROLE)
    except RoleNotFound:
        create_role(
            session,
            name=COMMUNITY_ROLE,
            actor=actor,
            description="Anyone asking the community version: reading the law, nothing more",
            permissions=(DOCUMENTS_READ,),
        )

    try:
        owner = get_user(session, COMMUNITY_EMAIL)
    except UserNotFound:
        owner = create_user(
            session,
            email=COMMUNITY_EMAIL,
            display_name="Community",
            actor=actor,
            kind="service_account",
            roles=(COMMUNITY_ROLE,),
        )
    if owner.kind != "service_account":
        raise SurfaceOwnerIsAPerson(f"{owner.email} belongs to a person, not the community version")

    token = _working_token(session, owner)
    minted = token is None
    if token is None:
        token, _ = mint(
            session,
            email=owner.email,
            name=COMMUNITY_TOKEN,
            permissions=(DOCUMENTS_READ,),
            actor=actor,
        )
    write_shared(path, json.dumps({"user": str(owner.id), "token": str(token.id)}))
    return CommunityAccount(
        user_id=owner.id, token_id=token.id, token_prefix=token.prefix, minted=minted
    )


def _working_token(session: Session, owner: User) -> PersonalAccessToken | None:
    """The account's newest token that is neither revoked nor expired."""
    return session.scalars(
        select(PersonalAccessToken)
        .where(
            PersonalAccessToken.user_id == owner.id,
            PersonalAccessToken.revoked_at.is_(None),
            or_(
                PersonalAccessToken.expires_at.is_(None),
                PersonalAccessToken.expires_at > datetime.now(UTC),
            ),
        )
        .order_by(PersonalAccessToken.created_at.desc())
    ).first()
