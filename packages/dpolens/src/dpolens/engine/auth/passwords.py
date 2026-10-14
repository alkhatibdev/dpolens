"""Passwords, for the one surface that has them.

Argon2id with argon2-cffi's defaults, which follow RFC 9106's second recommended
option. A hash made with older parameters is replaced the next time its owner
signs in, so raising the cost later reaches every account that is used.

There is no composition rule, only a length, which is what NIST SP 800-63B asks
for: a long password is a strong one, and rules about symbols mostly produce
passwords people write down.
"""

from __future__ import annotations

from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import DashboardSession, User
from dpolens.engine.auth.users import get_user
from dpolens.engine.logs.governance import USER_PASSWORD_SET, Actor, record

MIN_LENGTH = 12
MAX_LENGTH = 1024
"""Long enough for any passphrase, short enough that nobody can make the server
hash a megabyte to answer one sign-in."""

_hasher = PasswordHasher()


class WeakPassword(Exception):
    """A password the instance will not store."""


class NoPasswordAllowed(Exception):
    """A service account or an erased account cannot be given a password."""


@cache
def _decoy() -> str:
    """A hash to check against when there is no real one, made once per process."""
    return _hasher.hash("a password that belongs to nobody")


def check_strength(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"a password needs at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise WeakPassword(f"a password can be at most {MAX_LENGTH} characters")


def hash_password(password: str) -> str:
    check_strength(password)
    return _hasher.hash(password)


def verify(stored: str | None, password: str) -> bool:
    """Whether `password` matches `stored`.

    Without a stored hash the password is still checked, against a decoy, so the
    time an answer takes does not say whether the account exists.
    """
    try:
        return _hasher.verify(stored or _decoy(), password) and stored is not None
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


def rehash(password: str) -> str:
    """A fresh hash of a password that has just been verified.

    No length check: a password set before a stricter rule is still the
    password, and the rule applies when it is next changed.
    """
    return _hasher.hash(password)


def set_password(session: Session, *, email: str, password: str, actor: Actor) -> User:
    """Give a person a new password, and sign them out everywhere.

    Ending their sessions is the point of a reset: whoever knew the old password
    may be signed in with it.
    """
    user = get_user(session, email)
    if user.kind != "person":
        raise NoPasswordAllowed(f"{user.email} is a service account, which signs in with tokens")
    if user.status == "erased":
        raise NoPasswordAllowed("an erased account cannot be given a password")

    user.password_hash = hash_password(password)
    ended = session.execute(delete(DashboardSession).where(DashboardSession.user_id == user.id))
    session.flush()
    record(
        session,
        actor=actor,
        action=USER_PASSWORD_SET,
        target_type="user",
        target_id=str(user.id),
        details={"sessions_ended": ended.rowcount},  # type: ignore[attr-defined]
    )
    return user
