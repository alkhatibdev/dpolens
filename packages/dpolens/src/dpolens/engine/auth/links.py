"""Sign-in links: how a person added in the dashboard chooses a password, with no email.

A link carries a 256-bit random value, shown once to whoever made it; only its
SHA-256 is stored, as for a session or a token. It works once, for three days,
and a newer link for the same person deletes the older one, so there is never
more than one to leak.

Until it is used, the person's old password keeps working. A link that ended a
password the moment it was made would let whoever can make links lock anyone out.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import DashboardSession, SignInLink, User
from dpolens.engine.auth.passwords import check_strength, give_password
from dpolens.engine.auth.sessions import Lifetimes, digest_of, open_session
from dpolens.engine.logs.governance import USER_SIGN_IN_LINK_CREATED, Actor, record

LIFETIME = timedelta(hours=72)
SECRET_BYTES = 32


class LinkNotAllowed(Exception):
    """Nobody can sign in through a link to this account."""


class LinkUnusable(Exception):
    """The link is unknown, spent or past its time.

    The person holding it gets one answer whichever it is; `reason` is for
    telemetry.
    """

    def __init__(self, reason: str) -> None:
        super().__init__("this sign-in link no longer works")
        self.reason = reason


def make_link(
    session: Session, *, user: User, actor: Actor, now: datetime | None = None
) -> tuple[SignInLink, str]:
    """A new link for `user`, ending any earlier one, with its secret returned once."""
    if user.kind != "person":
        raise LinkNotAllowed(f"{user.email} is a service account, which signs in with tokens")
    if user.status != "active":
        raise LinkNotAllowed(f"{user.email} is {user.status}, so a link would never work")

    now = now or datetime.now(UTC)
    session.execute(delete(SignInLink).where(SignInLink.user_id == user.id))
    secret = secrets.token_urlsafe(SECRET_BYTES)
    row = SignInLink(
        user_id=user.id,
        token_hash=digest_of(secret),
        expires_at=now + LIFETIME,
        created_by_user_id=actor.user_id,
    )
    session.add(row)
    session.flush()
    record(
        session,
        actor=actor,
        action=USER_SIGN_IN_LINK_CREATED,
        target_type="user",
        target_id=str(user.id),
        details={"expires_at": row.expires_at.isoformat()},
    )
    return row, secret


def live_links(session: Session, *, now: datetime | None = None) -> dict[str, datetime]:
    """When each person's unused link runs out, by user id, for a list of people."""
    now = now or datetime.now(UTC)
    rows = session.execute(
        select(SignInLink.user_id, SignInLink.expires_at).where(SignInLink.expires_at > now)
    ).all()
    return {str(user_id): expires_at for user_id, expires_at in rows}


def usable_link(
    session: Session, *, secret: str, now: datetime | None = None, lock: bool = False
) -> SignInLink:
    """The link a secret names, if it may still be used, without spending it.

    `lock` is for spending it: two tabs spending one link cannot both succeed.
    Only this table is locked, because the owner is joined in and Postgres will not
    lock the outer side of a join.
    """
    now = now or datetime.now(UTC)
    query = select(SignInLink).where(SignInLink.token_hash == digest_of(secret))
    if lock:
        query = query.with_for_update(of=SignInLink)
    row = session.scalars(query).first()
    if row is None:
        raise LinkUnusable("unknown")
    if row.expires_at <= now:
        raise LinkUnusable("expired")
    if row.user.kind != "person" or row.user.status != "active":
        raise LinkUnusable("owner_inactive")
    return row


def redeem(
    session: Session,
    *,
    secret: str,
    password: str,
    lifetimes: Lifetimes,
    now: datetime | None = None,
) -> tuple[DashboardSession, str]:
    """Spend a link: set the password it was made for, and sign its owner in.

    The password is checked before the link is spent, so a person who chose one
    too short can try again with the same link.
    """
    row = usable_link(session, secret=secret, now=now, lock=True)
    user = row.user
    check_strength(password)
    session.delete(row)
    give_password(
        session,
        user=user,
        password=password,
        actor=Actor(user_id=user.id, via="dashboard"),
        method="sign_in_link",
    )
    return open_session(session, user=user, lifetimes=lifetimes, now=now)


def purge_expired_links(session: Session, *, now: datetime | None = None) -> int:
    """Delete links whose time has run out. A used link is deleted when it is used."""
    now = now or datetime.now(UTC)
    deleted = session.execute(delete(SignInLink).where(SignInLink.expires_at <= now))
    session.flush()
    return int(deleted.rowcount)  # type: ignore[attr-defined]
