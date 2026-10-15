"""Reading the governance log back for a person: a page of entries, with names for the ids.

An entry names people and tokens by id, which is what the hash covers and what
keeps an export verifiable after an erasure. A page needs names, so they are
looked up here, for the entries on the page only.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Text, and_, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from dpolens.engine.auth.models import PersonalAccessToken, User
from dpolens.engine.logs.models import GovernanceEntry


@dataclass(frozen=True)
class EntryView:
    seq: int
    occurred_at: datetime
    action: str
    target_type: str
    target_id: str
    details: dict[str, Any]
    entry_hash: str
    prev_hash: str
    actor: User | None
    actor_token: PersonalAccessToken | None
    target_user: User | None
    target_token: PersonalAccessToken | None


@dataclass(frozen=True)
class EntryFilter:
    actor_id: uuid.UUID | None = None
    actions: tuple[str, ...] = ()
    """Action names, or prefixes ending in a dot, such as `session.`."""
    since: datetime | None = None
    until: datetime | None = None
    text: str | None = None
    """Words in a name, an address, a token, a role, an action or what changed."""


@dataclass(frozen=True)
class EntryPage:
    entries: tuple[EntryView, ...]
    total: int
    next_before: int | None


def _like(words: str) -> str:
    escaped = words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _conditions(found: EntryFilter) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if found.actor_id is not None:
        conditions.append(GovernanceEntry.actor_user_id == found.actor_id)
    if found.actions:
        conditions.append(
            or_(
                *(
                    GovernanceEntry.action.startswith(action)
                    if action.endswith(".")
                    else GovernanceEntry.action == action
                    for action in found.actions
                )
            )
        )
    if found.since is not None:
        conditions.append(GovernanceEntry.occurred_at >= found.since)
    if found.until is not None:
        conditions.append(GovernanceEntry.occurred_at < found.until)
    if found.text:
        pattern = _like(found.text)
        actor = aliased(User)
        target = aliased(User)
        token = aliased(PersonalAccessToken)
        named = select(GovernanceEntry.seq).outerjoin(
            actor, actor.id == GovernanceEntry.actor_user_id
        )
        named = named.outerjoin(
            target,
            and_(
                GovernanceEntry.target_type == "user",
                cast(target.id, Text) == GovernanceEntry.target_id,
            ),
        ).outerjoin(
            token,
            or_(
                token.id == GovernanceEntry.actor_pat_id,
                and_(
                    GovernanceEntry.target_type == "personal_access_token",
                    cast(token.id, Text) == GovernanceEntry.target_id,
                ),
            ),
        )
        conditions.append(
            GovernanceEntry.seq.in_(
                named.where(
                    or_(
                        GovernanceEntry.action.ilike(pattern, escape="\\"),
                        GovernanceEntry.target_id.ilike(pattern, escape="\\"),
                        cast(GovernanceEntry.details, Text).ilike(pattern, escape="\\"),
                        actor.display_name.ilike(pattern, escape="\\"),
                        actor.email.ilike(pattern, escape="\\"),
                        target.display_name.ilike(pattern, escape="\\"),
                        target.email.ilike(pattern, escape="\\"),
                        token.name.ilike(pattern, escape="\\"),
                        token.prefix.ilike(pattern, escape="\\"),
                    )
                )
            )
        )
    return conditions


def _ids(values: Sequence[str]) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()
    for value in values:
        try:
            found.add(uuid.UUID(value))
        except ValueError:
            continue
    return found


def page_of_entries(
    session: Session, found: EntryFilter, *, limit: int, before: int | None = None
) -> EntryPage:
    """The newest entries first, a page at a time, with the names their ids stand for."""
    conditions = _conditions(found)
    total = session.scalar(select(func.count()).select_from(GovernanceEntry).where(*conditions))
    query = select(
        GovernanceEntry, cast(GovernanceEntry.details, Text).label("details_text")
    ).where(*conditions)
    if before is not None:
        query = query.where(GovernanceEntry.seq < before)
    rows = session.execute(query.order_by(GovernanceEntry.seq.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    shown = rows[:limit]

    user_ids = {row[0].actor_user_id for row in shown if row[0].actor_user_id is not None}
    user_ids |= _ids([row[0].target_id for row in shown if row[0].target_type == "user"])
    token_ids = {row[0].actor_pat_id for row in shown if row[0].actor_pat_id is not None}
    token_ids |= _ids(
        [row[0].target_id for row in shown if row[0].target_type == "personal_access_token"]
    )
    users = (
        {user.id: user for user in session.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    tokens = (
        {
            token.id: token
            for token in session.scalars(
                select(PersonalAccessToken).where(PersonalAccessToken.id.in_(token_ids))
            )
        }
        if token_ids
        else {}
    )

    def target_of(entry: GovernanceEntry, kind: str) -> uuid.UUID | None:
        if entry.target_type != kind:
            return None
        matched = _ids([entry.target_id])
        return next(iter(matched), None)

    views = []
    for entry, details_text in shown:
        target_user = target_of(entry, "user")
        target_token = target_of(entry, "personal_access_token")
        views.append(
            EntryView(
                seq=entry.seq,
                occurred_at=entry.occurred_at,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                details=json.loads(details_text),
                entry_hash=bytes(entry.entry_hash).hex(),
                prev_hash=bytes(entry.prev_hash).hex(),
                actor=users.get(entry.actor_user_id) if entry.actor_user_id else None,
                actor_token=tokens.get(entry.actor_pat_id) if entry.actor_pat_id else None,
                target_user=users.get(target_user) if target_user else None,
                target_token=tokens.get(target_token) if target_token else None,
            )
        )
    return EntryPage(
        entries=tuple(views),
        total=int(total or 0),
        next_before=shown[-1][0].seq if more and shown else None,
    )


def actors(session: Session) -> list[User]:
    """Everyone who appears in the log as having acted, for choosing whose entries to show."""
    return list(
        session.scalars(
            select(User)
            .where(
                User.id.in_(
                    select(GovernanceEntry.actor_user_id)
                    .where(GovernanceEntry.actor_user_id.is_not(None))
                    .distinct()
                )
            )
            .order_by(func.lower(User.display_name))
        )
    )
