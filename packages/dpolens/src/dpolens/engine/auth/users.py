"""Creating users, assigning roles, and the guard that keeps someone in charge.

A governance entry names a user by id and never by email address. The id is what
the hash covers, and an export keeps identities in a file of their own, so the
chain stays verifiable after somebody exercises their right to erasure.

The lockout guard lives here rather than in a surface, so the CLI is bound by it
exactly as the API will be. It is checked after the change has been
staged and before the transaction commits, which is the only point where the
question "would this leave nobody able to manage roles" has a true answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import Role, User, role_permissions, user_roles
from dpolens.engine.auth.permissions import ROLES_MANAGE
from dpolens.engine.logs.governance import (
    USER_ACTIVATED,
    USER_CREATED,
    USER_DEACTIVATED,
    USER_ROLE_GRANTED,
    USER_ROLE_REVOKED,
    Actor,
    record,
)


class UserNotFound(Exception):
    """No user with that email address."""


class DuplicateEmail(Exception):
    """That email address already belongs to a user."""


class RoleNotFound(Exception):
    """No role with that name."""


class LockoutRefused(Exception):
    """The change would leave nobody able to manage roles."""


class UserErased(Exception):
    """The account was erased, and erasure is not reversible."""


def normalise_email(email: str) -> str:
    """Addresses are compared case-insensitively, so they are stored that way."""
    return email.strip().lower()


def get_user(session: Session, email: str) -> User:
    user = session.scalars(select(User).where(User.email == normalise_email(email))).first()
    if user is None:
        raise UserNotFound(f"no user with the email {normalise_email(email)}")
    return user


def get_role(session: Session, name: str) -> Role:
    role = session.scalars(select(Role).where(Role.name == name)).first()
    if role is None:
        raise RoleNotFound(f"no role named {name!r}. `dpolens role list` shows the ones there are")
    return role


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.email)).all())


def managers(session: Session) -> list[User]:
    """Active people who can manage roles. Service accounts do not count."""
    return list(
        session.scalars(
            select(User)
            .join(user_roles, User.id == user_roles.c.user_id)
            .join(role_permissions, user_roles.c.role_id == role_permissions.c.role_id)
            .where(
                role_permissions.c.permission_key == ROLES_MANAGE,
                User.status == "active",
                User.kind == "person",
            )
            .distinct()
        ).all()
    )


@contextmanager
def lockout_guard(session: Session, what: str) -> Iterator[None]:
    """Refuse a change that takes away the last person who can manage roles.

    The question is whether the change removes the last one, not whether there is
    one: on a fresh instance nobody holds anything yet, and deleting an unused
    role there locks nobody out. The recovery path is creating another
    administrator, so there is no flag to force this.
    """
    had_one = bool(managers(session))
    yield
    session.flush()
    if had_one and not managers(session):
        raise LockoutRefused(
            f"{what} would leave no active person holding {ROLES_MANAGE}. "
            "Grant it to somebody else first."
        )


def create_user(
    session: Session,
    *,
    email: str,
    display_name: str,
    actor: Actor,
    kind: str = "person",
    roles: tuple[str, ...] = (),
) -> User:
    """Create a person or a service account. Passwords arrive with login."""
    address = normalise_email(email)
    if session.scalars(select(User).where(User.email == address)).first() is not None:
        raise DuplicateEmail(f"{address} already belongs to a user")

    user = User(
        email=address,
        display_name=display_name,
        kind=kind,
        roles=[get_role(session, name) for name in roles],
    )
    session.add(user)
    session.flush()
    record(
        session,
        actor=actor,
        action=USER_CREATED,
        target_type="user",
        target_id=str(user.id),
        details={"kind": kind, "roles": sorted(roles)},
    )
    return user


def grant_role(session: Session, *, email: str, role_name: str, actor: Actor) -> User:
    user = get_user(session, email)
    role = get_role(session, role_name)
    if role in user.roles:
        return user

    user.roles.append(role)
    session.flush()
    record(
        session,
        actor=actor,
        action=USER_ROLE_GRANTED,
        target_type="user",
        target_id=str(user.id),
        details={"role": role.name},
    )
    return user


def revoke_role(session: Session, *, email: str, role_name: str, actor: Actor) -> User:
    user = get_user(session, email)
    role = get_role(session, role_name)
    if role not in user.roles:
        return user

    with lockout_guard(session, f"taking {role.name} from {user.email}"):
        user.roles.remove(role)
    record(
        session,
        actor=actor,
        action=USER_ROLE_REVOKED,
        target_type="user",
        target_id=str(user.id),
        details={"role": role.name},
    )
    return user


def deactivate(session: Session, *, email: str, actor: Actor) -> User:
    """Block access and keep the row, so log entries still name somebody."""
    user = get_user(session, email)
    if user.status == "erased":
        raise UserErased(f"{user.email} is erased, which cannot be undone")
    if user.status == "deactivated":
        return user

    with lockout_guard(session, f"deactivating {user.email}"):
        user.status = "deactivated"
        user.deactivated_at = datetime.now(UTC)
    record(
        session,
        actor=actor,
        action=USER_DEACTIVATED,
        target_type="user",
        target_id=str(user.id),
    )
    return user


def activate(session: Session, *, email: str, actor: Actor) -> User:
    user = get_user(session, email)
    if user.status == "erased":
        raise UserErased(f"{user.email} is erased, which cannot be undone")
    if user.status == "active":
        return user

    user.status = "active"
    user.deactivated_at = None
    session.flush()
    record(
        session,
        actor=actor,
        action=USER_ACTIVATED,
        target_type="user",
        target_id=str(user.id),
    )
    return user
