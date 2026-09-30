"""Roles: freely named bundles of catalog permissions, editable at runtime.

Seeded roles are ordinary roles. They can be renamed, re-permissioned or
deleted, and the only thing stopping a delete is somebody still holding it.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import Permission, Role, User, user_roles
from dpolens.engine.auth.permissions import PERMISSIONS, unknown
from dpolens.engine.auth.users import get_role, lockout_guard
from dpolens.engine.logs.governance import (
    ROLE_CREATED,
    ROLE_DELETED,
    ROLE_PERMISSIONS_CHANGED,
    Actor,
    record,
)


class DuplicateRole(Exception):
    """A role with that name already exists."""


class RoleInUse(Exception):
    """Users still hold this role, so it cannot be deleted."""


class UnknownPermission(Exception):
    """That permission is not in the catalog."""


def list_roles(session: Session) -> list[Role]:
    return list(session.scalars(select(Role).order_by(Role.name)).all())


def holders(session: Session, role: Role) -> list[User]:
    return list(
        session.scalars(
            select(User)
            .join(user_roles, User.id == user_roles.c.user_id)
            .where(user_roles.c.role_id == role.id)
            .order_by(User.email)
        ).all()
    )


def check_known(keys: Iterable[str]) -> None:
    """Refuse anything outside the catalog, and say what the catalog holds."""
    missing = unknown(keys)
    if missing:
        raise UnknownPermission(
            f"{', '.join(missing)} is not in the permission catalog. "
            f"The catalog holds: {', '.join(sorted(PERMISSIONS))}"
        )


def create_role(
    session: Session,
    *,
    name: str,
    actor: Actor,
    description: str = "",
    permissions: tuple[str, ...] = (),
) -> Role:
    if session.scalars(select(Role).where(Role.name == name)).first() is not None:
        raise DuplicateRole(f"a role named {name!r} already exists")
    check_known(permissions)

    role = Role(
        name=name,
        description=description,
        permissions=list(
            session.scalars(select(Permission).where(Permission.key.in_(permissions))).all()
        ),
    )
    session.add(role)
    session.flush()
    record(
        session,
        actor=actor,
        action=ROLE_CREATED,
        target_type="role",
        target_id=role.name,
        details={"permissions": sorted(permissions)},
    )
    return role


def grant_permission(session: Session, *, role_name: str, permission: str, actor: Actor) -> Role:
    check_known((permission,))
    role = get_role(session, role_name)
    before = role.permission_keys()
    if permission in before:
        return role

    role.permissions.append(session.get_one(Permission, permission))
    session.flush()
    record(
        session,
        actor=actor,
        action=ROLE_PERMISSIONS_CHANGED,
        target_type="role",
        target_id=role.name,
        details={
            "granted": permission,
            "before": sorted(before),
            "after": sorted(role.permission_keys()),
        },
    )
    return role


def revoke_permission(session: Session, *, role_name: str, permission: str, actor: Actor) -> Role:
    check_known((permission,))
    role = get_role(session, role_name)
    before = role.permission_keys()
    if permission not in before:
        return role

    with lockout_guard(session, f"taking {permission} from {role.name}"):
        role.permissions = [row for row in role.permissions if row.key != permission]
    record(
        session,
        actor=actor,
        action=ROLE_PERMISSIONS_CHANGED,
        target_type="role",
        target_id=role.name,
        details={
            "revoked": permission,
            "before": sorted(before),
            "after": sorted(role.permission_keys()),
        },
    )
    return role


def delete_role(session: Session, *, role_name: str, actor: Actor) -> None:
    """Delete a role nobody holds. Reassign the holders first, by design."""
    role = get_role(session, role_name)
    held_by = holders(session, role)
    if held_by:
        listed = ", ".join(user.email for user in held_by)
        raise RoleInUse(
            f"{role.name} is held by {listed}. Take the role away from them first, so "
            "nobody loses access without somebody deciding to."
        )

    keys = sorted(role.permission_keys())
    was_seeded = role.is_seeded
    with lockout_guard(session, f"deleting {role.name}"):
        session.delete(role)
    record(
        session,
        actor=actor,
        action=ROLE_DELETED,
        target_type="role",
        target_id=role.name,
        details={"permissions": keys, "was_seeded": was_seeded},
    )
