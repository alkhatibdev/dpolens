"""Signing in to the dashboard, and the sessions that follow.

A session is a 256-bit random value the browser holds in a cookie it cannot read
from script; the API keeps only its SHA-256, as it does for a token. A session
ends when its lifetime runs out whatever happens, and sooner when nobody has used
it for the idle timeout. Every request checks the owner, so deactivating a user
stops their sessions on the next request rather than at the next expiry.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import DashboardSession, User
from dpolens.engine.auth.passwords import needs_rehash, rehash, verify
from dpolens.engine.auth.users import normalise_email
from dpolens.engine.logs.governance import (
    SESSION_ENDED,
    SESSION_REFUSED,
    SESSION_STARTED,
    Actor,
    record,
)

SECRET_BYTES = 32

SEEN_AT_RESOLUTION = timedelta(seconds=60)
"""How stale `last_seen_at` may be before a request writes it again, so a page
that makes ten calls does not make ten writes. A minute is nothing against an
idle timeout measured in tens of minutes."""


@dataclass(frozen=True)
class Lifetimes:
    idle: timedelta
    absolute: timedelta


class SignInRefused(Exception):
    """The email and password do not open an account.

    Said the same way whatever the cause, so the answer does not tell anyone which
    accounts exist. `user` and `reason` are for the governance log, never for the
    person signing in.
    """

    def __init__(self, user: User | None, reason: str) -> None:
        super().__init__("that email and password do not match an account")
        self.user = user
        self.reason = reason


class UnknownSession(Exception):
    """No session matches the cookie: it never existed, or it was signed out."""


class SessionEnded(Exception):
    """A session that existed and no longer works."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the session has ended: {reason}")
        self.reason = reason


def digest_of(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def sign_in(
    session: Session,
    *,
    email: str,
    password: str,
    lifetimes: Lifetimes,
    now: datetime | None = None,
) -> tuple[DashboardSession, str]:
    """Open a session for a person whose password matches, and return its secret once."""
    now = now or datetime.now(UTC)
    user = session.scalar(select(User).where(User.email == normalise_email(email)))
    if user is None:
        verify(None, password)
        raise SignInRefused(None, "unknown_email")
    stored = user.password_hash
    matched = verify(stored, password)
    if stored is None or not matched:
        raise SignInRefused(user, "no_password" if stored is None else "wrong_password")
    if user.kind != "person" or user.status != "active":
        raise SignInRefused(user, "not_active" if user.kind == "person" else "service_account")

    if needs_rehash(stored):
        user.password_hash = rehash(password)

    return open_session(session, user=user, lifetimes=lifetimes, now=now)


def open_session(
    session: Session, *, user: User, lifetimes: Lifetimes, now: datetime | None = None
) -> tuple[DashboardSession, str]:
    """Start a session for somebody already proven to be who they are, returning its secret once."""
    now = now or datetime.now(UTC)
    secret = secrets.token_urlsafe(SECRET_BYTES)
    row = DashboardSession(
        user_id=user.id,
        token_hash=digest_of(secret),
        expires_at=now + lifetimes.absolute,
        last_seen_at=now,
    )
    session.add(row)
    session.flush()
    record(
        session,
        actor=Actor(user_id=user.id, via="dashboard"),
        action=SESSION_STARTED,
        target_type="dashboard_session",
        target_id=str(row.id),
        details={"expires_at": row.expires_at.isoformat()},
    )
    return row, secret


def record_refusal(session: Session, refused: SignInRefused) -> None:
    """Write a refused sign-in for an account that exists, which is the signal
    worth keeping: somebody is trying that account's password."""
    if refused.user is None:
        return
    record(
        session,
        actor=Actor(via="dashboard"),
        action=SESSION_REFUSED,
        target_type="user",
        target_id=str(refused.user.id),
        details={"reason": refused.reason},
    )


def resolve(
    session: Session, secret: str, *, lifetimes: Lifetimes, now: datetime | None = None
) -> DashboardSession:
    """The session a cookie names, if it may still be used."""
    now = now or datetime.now(UTC)
    row = session.scalar(
        select(DashboardSession).where(DashboardSession.token_hash == digest_of(secret))
    )
    if row is None:
        raise UnknownSession("no session matches")
    if row.expires_at <= now:
        raise SessionEnded("expired")
    if now - row.last_seen_at > lifetimes.idle:
        raise SessionEnded("idle")
    if row.user.status != "active":
        raise SessionEnded("owner_inactive")

    if now - row.last_seen_at >= SEEN_AT_RESOLUTION:
        row.last_seen_at = now
        session.flush()
    return row


def sign_out(session: Session, row: DashboardSession) -> None:
    session.delete(row)
    session.flush()
    record(
        session,
        actor=Actor(user_id=row.user_id, via="dashboard"),
        action=SESSION_ENDED,
        target_type="dashboard_session",
        target_id=str(row.id),
        details={"reason": "signed_out"},
    )


def purge_ended(session: Session, *, lifetimes: Lifetimes, now: datetime | None = None) -> int:
    """Delete the sessions that can no longer be used, and say how many."""
    now = now or datetime.now(UTC)
    deleted = session.execute(
        delete(DashboardSession).where(
            or_(
                DashboardSession.expires_at <= now,
                DashboardSession.last_seen_at < now - lifetimes.idle,
            )
        )
    )
    session.flush()
    return int(deleted.rowcount)  # type: ignore[attr-defined]
