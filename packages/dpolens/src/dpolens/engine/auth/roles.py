"""Roles: freely named bundles of catalog permissions, editable at runtime.

Seeded roles are ordinary roles. They can be renamed, re-permissioned or
deleted, and the only thing stopping a delete is somebody still holding it.

Every change raises the role's revision, from the command line too. A page that
saves against the revision it read is refused when somebody changed the role in
between, which is how two people editing one role learn of each other instead of
one silently undoing the other.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import Permission, Role, User, user_roles
from dpolens.engine.auth.permissions import PERMISSIONS, unknown
from dpolens.engine.auth.users import RoleNotFound, get_role, lockout_guard
from dpolens.engine.logs.governance import (
    ROLE_CREATED,
    ROLE_DELETED,
    ROLE_DESCRIBED,
    ROLE_PERMISSIONS_CHANGED,
    ROLE_RENAMED,
    Actor,
    record,
)


class DuplicateRole(Exception):
    """A role with that name already exists."""


class RoleInUse(Exception):
    """Users still hold this role, so it cannot be deleted. `holders` names them."""

    def __init__(self, message: str, holders: list[User]) -> None:
        super().__init__(message)
        self.holders = holders


class UnknownPermission(Exception):
    """That permission is not in the catalog."""


class StaleRole(Exception):
    """The role changed after the caller read it, so their change would undo another."""

    def __init__(self, role: Role) -> None:
        super().__init__(
            f"{role.name} changed after it was read: it is at revision {role.revision}"
        )
        self.role = role


def get_role_by_id(session: Session, role_id: uuid.UUID, *, for_update: bool = False) -> Role:
    """A role by id, locked against concurrent changes when it is about to be changed."""
    query = select(Role).where(Role.id == role_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    role = session.scalars(query).first()
    if role is None:
        raise RoleNotFound(f"no role with the id {role_id}")
    return role


def _check_revision(role: Role, expected: int | None) -> None:
    if expected is not None and role.revision != expected:
        raise StaleRole(role)


def _changed(role: Role, actor: Actor) -> None:
    role.revision += 1
    role.updated_at = datetime.now(UTC)
    role.updated_by_user_id = actor.user_id


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
        updated_by_user_id=actor.user_id,
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


def set_permissions(
    session: Session,
    *,
    role: Role,
    permissions: Iterable[str],
    actor: Actor,
    expected_revision: int | None = None,
) -> Role:
    """Make these exactly the role's permissions, in one change and one entry."""
    wanted = frozenset(permissions)
    check_known(wanted)
    _check_revision(role, expected_revision)
    before = role.permission_keys()
    if wanted == before:
        return role

    with lockout_guard(session, f"changing what {role.name} allows"):
        role.permissions = list(
            session.scalars(
                select(Permission).where(Permission.key.in_(wanted)).order_by(Permission.key)
            ).all()
        )
    _changed(role, actor)
    session.flush()
    record(
        session,
        actor=actor,
        action=ROLE_PERMISSIONS_CHANGED,
        target_type="role",
        target_id=role.name,
        details={
            "granted": sorted(wanted - before),
            "revoked": sorted(before - wanted),
            "before": sorted(before),
            "after": sorted(wanted),
        },
    )
    return role


def grant_permission(session: Session, *, role_name: str, permission: str, actor: Actor) -> Role:
    check_known((permission,))
    role = get_role(session, role_name)
    return set_permissions(
        session, role=role, permissions=role.permission_keys() | {permission}, actor=actor
    )


def revoke_permission(session: Session, *, role_name: str, permission: str, actor: Actor) -> Role:
    check_known((permission,))
    role = get_role(session, role_name)
    return set_permissions(
        session, role=role, permissions=role.permission_keys() - {permission}, actor=actor
    )


def rename_role(
    session: Session,
    *,
    role: Role,
    name: str,
    description: str,
    actor: Actor,
    expected_revision: int | None = None,
) -> Role:
    """Give a role a new name or description.

    Earlier entries in the governance log name the role as it was called then, so
    the entry for a rename carries both names and a reader can follow it.
    """
    _check_revision(role, expected_revision)
    before = {"name": role.name, "description": role.description}
    after = {"name": name, "description": description}
    if before == after:
        return role
    if name != role.name and session.scalars(select(Role).where(Role.name == name)).first():
        raise DuplicateRole(f"a role named {name!r} already exists")

    role.name = name
    role.description = description
    _changed(role, actor)
    session.flush()
    record(
        session,
        actor=actor,
        action=ROLE_RENAMED if before["name"] != name else ROLE_DESCRIBED,
        target_type="role",
        target_id=name,
        details={"before": before, "after": after},
    )
    return role


def edit_role(
    session: Session,
    *,
    role: Role,
    actor: Actor,
    expected_revision: int | None = None,
    name: str | None = None,
    description: str | None = None,
    permissions: Iterable[str] | None = None,
) -> Role:
    """Change any of a role's name, description and permissions, against one revision.

    The revision is checked once, before anything changes: a save that renames and
    re-permissions a role is one decision, made against what its author saw.
    """
    _check_revision(role, expected_revision)
    if name is not None or description is not None:
        rename_role(
            session,
            role=role,
            name=role.name if name is None else name,
            description=role.description if description is None else description,
            actor=actor,
        )
    if permissions is not None:
        set_permissions(session, role=role, permissions=permissions, actor=actor)
    return role


def delete_role(session: Session, *, role_name: str, actor: Actor) -> None:
    """Delete a role nobody holds. Reassign the holders first, by design."""
    role = get_role(session, role_name)
    held_by = holders(session, role)
    if held_by:
        listed = ", ".join(user.email for user in held_by)
        raise RoleInUse(
            f"{role.name} is held by {listed}. Take the role away from them first, so "
            "nobody loses access without somebody deciding to.",
            held_by,
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
