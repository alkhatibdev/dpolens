"""What the pages for people, roles and tokens read, each in a handful of queries.

A route turns these into a response without building a query of its own, and a
page of fifty people costs the same few queries as a page of five.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from dpolens.engine.auth.links import live_links
from dpolens.engine.auth.models import PersonalAccessToken, Role, User, user_roles


@dataclass(frozen=True)
class PersonRow:
    user: User
    working_tokens: int
    link_expires_at: datetime | None
    acts_for_others: bool
    """Holds a working token trusted to act for other people, as the MCP server's account does."""


@dataclass(frozen=True)
class RoleRow:
    role: Role
    holders: list[User]


def _working(now: datetime) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """The conditions for a token that still works, its owner aside."""
    return (
        PersonalAccessToken.revoked_at.is_(None),
        or_(PersonalAccessToken.expires_at.is_(None), PersonalAccessToken.expires_at > now),
    )


def people(session: Session) -> list[PersonRow]:
    """Everyone, people before service accounts, each by name."""
    now = datetime.now(UTC)
    users = session.scalars(select(User).order_by(User.kind, func.lower(User.display_name))).all()
    counts: dict[uuid.UUID, int] = {
        user_id: count
        for user_id, count in session.execute(
            select(PersonalAccessToken.user_id, func.count())
            .where(*_working(now))
            .group_by(PersonalAccessToken.user_id)
        ).all()
    }
    links = live_links(session, now=now)
    surfaces = _surfaces(session, now)
    return [
        PersonRow(
            user=user,
            working_tokens=int(counts.get(user.id, 0)),
            link_expires_at=links.get(str(user.id)),
            acts_for_others=user.id in surfaces,
        )
        for user in users
    ]


def _surfaces(session: Session, now: datetime) -> set[uuid.UUID]:
    return set(
        session.scalars(
            select(PersonalAccessToken.user_id).where(
                PersonalAccessToken.trusted_surface.is_(True), *_working(now)
            )
        ).all()
    )


def person(session: Session, user: User) -> PersonRow:
    now = datetime.now(UTC)
    count = session.scalar(
        select(func.count())
        .select_from(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user.id, *_working(now))
    )
    return PersonRow(
        user=user,
        working_tokens=int(count or 0),
        link_expires_at=live_links(session, now=now).get(str(user.id)),
        acts_for_others=user.id in _surfaces(session, now),
    )


def roles(session: Session) -> list[RoleRow]:
    """Every role with who holds it, in one query for the holders."""
    found = session.scalars(select(Role).order_by(func.lower(Role.name))).all()
    held: dict[uuid.UUID, list[User]] = {role.id: [] for role in found}
    for role_id, user in session.execute(
        select(user_roles.c.role_id, User)
        .join(User, User.id == user_roles.c.user_id)
        .order_by(User.kind, func.lower(User.display_name))
    ).all():
        held.setdefault(role_id, []).append(user)
    return [RoleRow(role=role, holders=held[role.id]) for role in found]


def role(session: Session, found: Role) -> RoleRow:
    holders = session.scalars(
        select(User)
        .join(user_roles, User.id == user_roles.c.user_id)
        .where(user_roles.c.role_id == found.id)
        .order_by(User.kind, func.lower(User.display_name))
    ).all()
    return RoleRow(role=found, holders=list(holders))


def tokens(session: Session, *, owner: User | None) -> list[PersonalAccessToken]:
    """One person's tokens, or everybody's, the most recently used first."""
    query = select(PersonalAccessToken).order_by(
        PersonalAccessToken.last_used_at.desc().nulls_last(),
        PersonalAccessToken.created_at.desc(),
    )
    if owner is not None:
        query = query.where(PersonalAccessToken.user_id == owner.id)
    return list(session.scalars(query).all())
