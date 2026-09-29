"""Keeping the permission table equal to the code catalog, and seeding roles.

The sync writes no governance entry: it follows the code that is deployed, which
is a release rather than somebody's decision. Seeding a role does write one,
because a role is data and somebody has to be able to see where it came from.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import Permission, Role, role_permissions
from dpolens.engine.auth.permissions import (
    PERMISSIONS,
    SEEDED_ROLE_DESCRIPTIONS,
    SEEDED_ROLES,
)
from dpolens.engine.logs.governance import ROLE_SEEDED, Actor, record
from dpolens.engine.logs.models import GovernanceEntry


class StalePermission(Exception):
    """A role holds a permission this build no longer defines.

    Deleting it would quietly reduce someone's access, so the instance stops
    instead and names what has to be changed.
    """


def sync_catalog(session: Session) -> None:
    """Make the lookup table equal `permissions.PERMISSIONS`."""
    existing = {row.key: row for row in session.scalars(select(Permission)).all()}

    removed = set(existing) - set(PERMISSIONS)
    if removed:
        held = session.execute(
            select(Role.name, role_permissions.c.permission_key)
            .join(role_permissions, Role.id == role_permissions.c.role_id)
            .where(role_permissions.c.permission_key.in_(removed))
            .order_by(Role.name, role_permissions.c.permission_key)
        ).all()
        if held:
            listed = ", ".join(f"{name} holds {key}" for name, key in held)
            raise StalePermission(
                f"this build does not define {', '.join(sorted(removed))}, and {listed}. "
                "Revoke it from the role, or run a build that still defines it."
            )
        session.execute(delete(Permission).where(Permission.key.in_(removed)))

    for key, description in PERMISSIONS.items():
        row = existing.get(key)
        if row is None:
            session.add(Permission(key=key, description=description))
        elif row.description != description:
            row.description = description


def ensure_seeded_roles(session: Session, *, actor: Actor) -> list[str]:
    """Create Admin, DPO and Developer once, and never touch them again.

    "Once" is read from the governance log rather than from the roles table, so
    a role that somebody deliberately deleted does not come back on the next
    start. The log is append-only, which makes it the one record that cannot be
    lost.
    """
    already = set(
        session.scalars(
            select(GovernanceEntry.target_id).where(GovernanceEntry.action == ROLE_SEEDED)
        ).all()
    )

    created: list[str] = []
    for name, keys in SEEDED_ROLES.items():
        if name in already:
            continue
        if session.scalars(select(Role).where(Role.name == name)).first() is not None:
            continue
        role = Role(
            name=name,
            description=SEEDED_ROLE_DESCRIPTIONS[name],
            is_seeded=True,
            permissions=list(
                session.scalars(select(Permission).where(Permission.key.in_(keys))).all()
            ),
        )
        session.add(role)
        session.flush()
        record(
            session,
            actor=actor,
            action=ROLE_SEEDED,
            target_type="role",
            target_id=role.name,
            details={"permissions": sorted(keys)},
        )
        created.append(name)
    return created


def bootstrap(session: Session, *, actor: Actor) -> list[str]:
    """What every surface runs before it serves anything: catalog, then roles."""
    sync_catalog(session)
    session.flush()
    return ensure_seeded_roles(session, actor=actor)
