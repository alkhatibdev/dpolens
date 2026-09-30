"""Minting, checking and revoking personal access tokens.

A token is `dpol_` and 32 random bytes. What is stored is its SHA-256, and the
lookup is by that digest, so the secret is never compared in Python and never
written anywhere but the one line that prints it at creation.

A token's permissions are fixed when it is created and can only narrow
afterwards: what a request gets is the token's set intersected with whatever its
owner holds at that moment. Losing a role, or being deactivated, therefore
limits every token that user owns, with nothing to update and no cache to wait
out.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import PersonalAccessToken, User
from dpolens.engine.auth.roles import check_known
from dpolens.engine.auth.users import get_user
from dpolens.engine.logs.governance import PAT_CREATED, PAT_REVOKED, Actor, record

SCHEME = "dpol_"
SECRET_BYTES = 32
PREFIX_LENGTH = 11
"""How much of a token is kept for display: the scheme and six characters."""

USED_AT_RESOLUTION = timedelta(seconds=60)
"""How stale `last_used_at` may be before a request writes it again.

A write per request would put a row update in front of every search to keep a
field current that a person reads once a month. A minute still shows a leaked
token in use to the hour.
"""


class PermissionsExceedOwner(Exception):
    """A token cannot be given permissions its owner does not hold."""


class OwnerCannotHoldTokens(Exception):
    """A deactivated or erased account cannot be given new credentials."""


class DelegationRefused(Exception):
    """An assertion about who a surface is acting for does not hold."""


class UnknownToken(Exception):
    """Nothing in this instance matches that token.

    Deliberately indistinguishable from a token that never existed: there is no
    owner to attribute it to and nothing to tell the caller about.
    """


class TokenNotFound(Exception):
    """No token matches that prefix."""


class AmbiguousPrefix(Exception):
    """That prefix matches more than one token."""


@dataclass(frozen=True)
class TokenRejected(Exception):
    """The token exists and may not be used, which is worth recording.

    `reason` is one of `revoked`, `expired` or `owner_inactive`. Unlike an
    unknown token, this one has an owner, so it is the signal that a leaked
    credential is in use.
    """

    reason: str
    token: PersonalAccessToken

    def __str__(self) -> str:
        return f"token {self.token.prefix} was refused: {self.reason}"


@dataclass(frozen=True)
class Authenticated:
    """Who is calling, and what they may do on this request."""

    token: PersonalAccessToken
    user: User
    permissions: frozenset[str]

    def may(self, permission: str) -> bool:
        return permission in self.permissions


def digest_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def looks_like_a_token(presented: str) -> bool:
    """A cheap shape check, so a header full of noise costs no query."""
    return presented.startswith(SCHEME) and len(presented) > PREFIX_LENGTH


def generate() -> tuple[str, str, str]:
    """A new token, with the digest to store and the prefix to show."""
    token = SCHEME + secrets.token_urlsafe(SECRET_BYTES)
    return token, digest_of(token), token[:PREFIX_LENGTH]


def effective_permissions(token: PersonalAccessToken, user: User) -> frozenset[str]:
    return frozenset(token.permissions) & user.effective_permissions()


def mint(
    session: Session,
    *,
    email: str,
    name: str,
    permissions: Iterable[str],
    actor: Actor,
    expires_at: datetime | None = None,
    trusted_surface: bool = False,
) -> tuple[PersonalAccessToken, str]:
    """Create a token and return it once, with the row that will outlive it."""
    requested = frozenset(permissions)
    check_known(requested)

    owner = get_user(session, email)
    if owner.status != "active":
        raise OwnerCannotHoldTokens(
            f"{owner.email} is {owner.status}, so a new token would never authenticate"
        )

    excess = requested - owner.effective_permissions()
    if excess:
        raise PermissionsExceedOwner(
            f"{owner.email} does not hold {', '.join(sorted(excess))}, so a token of theirs "
            "cannot either. Grant it to one of their roles first, or leave it out."
        )

    token, stored, prefix = generate()
    row = PersonalAccessToken(
        user_id=owner.id,
        name=name,
        token_hash=stored,
        prefix=prefix,
        permissions=sorted(requested),
        trusted_surface=trusted_surface,
        expires_at=expires_at,
    )
    session.add(row)
    session.flush()
    record(
        session,
        actor=actor,
        action=PAT_CREATED,
        target_type="personal_access_token",
        target_id=str(row.id),
        details={
            "owner_id": str(owner.id),
            "name": name,
            "prefix": prefix,
            "permissions": sorted(requested),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "trusted_surface": trusted_surface,
        },
    )
    return row, token


def _owner_if_usable(session: Session, row: PersonalAccessToken) -> User:
    """The owner of a token that may be used right now, or a refusal saying why."""
    if row.revoked_at is not None:
        raise TokenRejected("revoked", row)
    if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
        raise TokenRejected("expired", row)

    owner = session.get_one(User, row.user_id)
    if owner.status != "active":
        raise TokenRejected("owner_inactive", row)
    return owner


def authenticate(session: Session, presented: str) -> Authenticated:
    """Turn a token into who is calling, or refuse and say why."""
    if not looks_like_a_token(presented):
        raise UnknownToken("that is not a DPOLens token")

    row = session.scalars(
        select(PersonalAccessToken).where(PersonalAccessToken.token_hash == digest_of(presented))
    ).first()
    if row is None:
        raise UnknownToken("no token matches")

    owner = _owner_if_usable(session, row)
    return Authenticated(token=row, user=owner, permissions=effective_permissions(row, owner))


def authenticate_delegated(
    session: Session, *, user_id: uuid.UUID, pat_id: uuid.UUID
) -> Authenticated:
    """Who a trusted surface says it is acting for, checked rather than believed.

    The trust a surface is given is that it may name the caller, not that it may
    invent a token id. So the named token has to exist, still be usable, and
    belong to the named user, and the permissions are that token's intersected
    with that user's roles, exactly as if they had called directly.
    """
    row = session.get(PersonalAccessToken, pat_id)
    if row is None or row.user_id != user_id:
        raise DelegationRefused("the asserted token does not belong to the asserted user")

    owner = _owner_if_usable(session, row)
    return Authenticated(token=row, user=owner, permissions=effective_permissions(row, owner))


def touch(session: Session, token: PersonalAccessToken) -> bool:
    """Record that a token was used, at most once a minute. True when written."""
    now = datetime.now(UTC)
    if token.last_used_at is not None and now - token.last_used_at < USED_AT_RESOLUTION:
        return False
    token.last_used_at = now
    session.flush()
    return True


def find(session: Session, prefix: str) -> PersonalAccessToken:
    """The token a prefix names, refusing rather than guessing when it is unclear."""
    rows = session.scalars(
        select(PersonalAccessToken).where(PersonalAccessToken.prefix.startswith(prefix))
    ).all()
    if not rows:
        raise TokenNotFound(f"no token starts with {prefix}. `dpolens token list` shows them")
    if len(rows) > 1:
        raise AmbiguousPrefix(
            f"{prefix} matches {len(rows)} tokens. Use the whole prefix as `token list` prints it"
        )
    return rows[0]


def revoke(session: Session, *, prefix: str, actor: Actor) -> PersonalAccessToken:
    """Stop a token working, keeping the row because the query log points at it."""
    row = find(session, prefix)
    if row.revoked_at is not None:
        return row

    row.revoked_at = datetime.now(UTC)
    session.flush()
    record(
        session,
        actor=actor,
        action=PAT_REVOKED,
        target_type="personal_access_token",
        target_id=str(row.id),
        details={"owner_id": str(row.user_id), "name": row.name, "prefix": row.prefix},
    )
    return row


def list_tokens(session: Session, *, email: str | None = None) -> list[PersonalAccessToken]:
    query = select(PersonalAccessToken).order_by(PersonalAccessToken.created_at)
    if email is not None:
        query = query.where(PersonalAccessToken.user_id == get_user(session, email).id)
    return list(session.scalars(query).all())


def status_of(token: PersonalAccessToken) -> str:
    """What `token list` prints, in the order that matters to a reader."""
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at is not None and token.expires_at <= datetime.now(UTC):
        return "expired"
    if token.owner.status != "active":
        return f"owner {token.owner.status}"
    return "active"
