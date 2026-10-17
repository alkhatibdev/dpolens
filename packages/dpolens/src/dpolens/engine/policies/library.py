"""A policy in the library: its versions, and any two of them compared.

Each version is in force from its effective date until the next one takes effect, so a version
that another has replaced has a last day, and one published for a later date is scheduled. A
draft is listed only for those who review policies, and a discarded one never.

Comparing two versions follows each rule from one version to the next through the matches made
when each was uploaded and reviewed, rejected matches and fixes included, rather than matching
the two afresh: a clause of the later version continues a clause of the earlier one when every
version between them says so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import DocumentNode, DocumentVersion, NodeText, ParseFlag
from dpolens.engine.policies.store import (
    EarlierClause,
    PolicyNotFound,
    _change_of,
    _document,
    _label_for,
    _names,
)
from dpolens.engine.policies.versions import Change, Earlier, Later

State = Literal["draft", "scheduled", "in_force", "replaced"]


class SameVersion(Exception):
    """A version compared with itself."""


@dataclass(frozen=True)
class VersionEntry:
    number: int
    label: str
    """The label citations show; for a draft, the one it is published with."""

    state: State
    effective_date: date
    until: date | None
    """Its last day in force, once a later version is published to take over."""

    created_at: datetime
    created_by: str | None
    published_at: datetime | None
    published_by: str | None
    source_name: str | None
    source_format: str | None
    source_size: int | None
    flags: int | None = None
    """For a draft, every flag it has, and how many are still open."""

    open: int | None = None


@dataclass(frozen=True)
class History:
    slug: str
    title: str
    status: str
    versions: tuple[VersionEntry, ...]
    """The draft first, then the published versions, the latest to take effect first."""


@dataclass(frozen=True)
class VersionRef:
    number: int
    label: str
    effective_date: date


@dataclass(frozen=True)
class Compared:
    """A clause of the later version, and the clause of the earlier one it continues."""

    key: str
    label: str | None
    heading: str | None
    text: str
    change: Change
    earlier: EarlierClause | None


@dataclass(frozen=True)
class Comparison:
    slug: str
    title: str
    earlier: VersionRef
    later: VersionRef
    clauses: tuple[Compared, ...]
    """Every clause of the later version, in the file's order."""

    removed: tuple[EarlierClause, ...]
    """Clauses of the earlier version nothing in the later one continues."""

    changes: dict[str, int]


def _label(version: DocumentVersion) -> str:
    return version.version_label or str(version.version_number)


def list_versions(session: Session, slug: str, *, drafts: bool = False) -> History:
    """A policy's versions as the library shows them, with a draft only when `drafts`."""
    document = _document(session, slug)
    rows = session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.status.in_(("published", "draft") if drafts else ("published",)),
        )
        .order_by(DocumentVersion.effective_date.desc(), DocumentVersion.version_number.desc())
    ).all()
    names = _names(
        session,
        [*(v.created_by_user_id for v in rows), *(v.published_by_user_id for v in rows)],
    )
    published = [v for v in rows if v.status == "published"]
    labels = {v.version_label for v in published}
    today = date.today()
    current = next((v for v in published if v.effective_date <= today), None)

    def entry(version: DocumentVersion, state: State, until: date | None) -> VersionEntry:
        flags: int | None = None
        left: int | None = None
        if version.status == "draft":
            settled = session.execute(
                select(ParseFlag.accepted_at, ParseFlag.resolved_at).where(
                    ParseFlag.document_version_id == version.id
                )
            ).all()
            flags = len(settled)
            left = sum(1 for accepted, resolved in settled if accepted is None and resolved is None)
        return VersionEntry(
            number=version.version_number,
            label=_label_for(version, labels) if version.status == "draft" else _label(version),
            state=state,
            effective_date=version.effective_date,
            until=until,
            created_at=version.created_at,
            created_by=names.get(version.created_by_user_id)
            if version.created_by_user_id
            else None,
            published_at=version.published_at,
            published_by=names.get(version.published_by_user_id)
            if version.published_by_user_id
            else None,
            source_name=version.source_name,
            source_format=version.source_format,
            source_size=version.source_size,
            flags=flags,
            open=left,
        )

    entries = [entry(v, "draft", None) for v in rows if v.status == "draft"]
    for index, version in enumerate(published):
        after = published[index - 1] if index > 0 else None
        until = after.effective_date - timedelta(days=1) if after is not None else None
        if version.effective_date > today:
            state: State = "scheduled"
        elif current is not None and version.id == current.id:
            state = "in_force"
        else:
            state = "replaced"
        entries.append(entry(version, state, until))
    return History(
        slug=document.slug, title=document.title, status=document.status, versions=tuple(entries)
    )


def _published(session: Session, slug: str, number: int) -> DocumentVersion:
    document = _document(session, slug)
    found = session.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version_number == number,
            DocumentVersion.status == "published",
        )
    ).first()
    if found is None:
        raise PolicyNotFound(f"{slug} has no published version {number}.")
    return found


def compare(session: Session, slug: str, first: int, second: int) -> Comparison:
    """Two published versions of a policy, clause by clause, the earlier of them first."""
    document = _document(session, slug)
    one, other = _published(session, slug, first), _published(session, slug, second)
    if one.id == other.id:
        raise SameVersion(f"Version {_label(one)} is the same version. Choose two different ones.")
    earlier, later = sorted((one, other), key=lambda version: version.effective_date)
    between = session.scalars(
        select(DocumentVersion.id).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.status == "published",
            DocumentVersion.effective_date >= earlier.effective_date,
            DocumentVersion.effective_date <= later.effective_date,
        )
    ).all()
    rows = session.execute(
        select(DocumentNode, NodeText)
        .join(NodeText, NodeText.node_id == DocumentNode.id)
        .where(DocumentNode.document_version_id.in_(between), NodeText.is_authoritative)
    ).all()
    nodes = {node.id: node for node, _ in rows}
    texts = {node.id: text for node, text in rows}

    def ordered(version: DocumentVersion) -> list[DocumentNode]:
        children: dict[uuid.UUID | None, list[DocumentNode]] = {}
        for node in nodes.values():
            if node.document_version_id == version.id:
                children.setdefault(node.parent_node_id, []).append(node)

        def walk(parent: uuid.UUID | None) -> list[DocumentNode]:
            found: list[DocumentNode] = []
            for node in sorted(children.get(parent, []), key=lambda n: n.order_index):
                found.extend([node, *walk(node.id)])
            return found

        return walk(None)

    def earlier_of(node: DocumentNode) -> DocumentNode | None:
        """Back through each version between, along the matches made when it was uploaded."""
        current: DocumentNode | None = node
        while current is not None and current.document_version_id != earlier.id:
            back = current.previous_node_id
            current = nodes.get(back) if back is not None else None
        return current

    def clause(node: DocumentNode) -> EarlierClause:
        text = texts[node.id]
        return EarlierClause(
            key=node.canonical_key, label=node.label, heading=text.heading, text=text.body_text
        )

    compared: list[Compared] = []
    continued: set[uuid.UUID] = set()
    changes = {"added": 0, "modified": 0, "moved": 0, "unchanged": 0}
    for node in ordered(later):
        text = texts[node.id]
        before = earlier_of(node)
        new = Later(node.canonical_key, node.label, text.heading, text.body_text)
        old = None
        if before is not None:
            continued.add(before.id)
            was = texts[before.id]
            old = Earlier(before.id, before.canonical_key, before.label, was.heading, was.body_text)
        change = _change_of(new, old)
        changes[change] += 1
        compared.append(
            Compared(
                key=node.canonical_key,
                label=node.label,
                heading=text.heading,
                text=text.body_text,
                change=change,
                earlier=clause(before) if before is not None else None,
            )
        )
    removed = tuple(clause(node) for node in ordered(earlier) if node.id not in continued)
    return Comparison(
        slug=document.slug,
        title=document.title,
        earlier=VersionRef(earlier.version_number, _label(earlier), earlier.effective_date),
        later=VersionRef(later.version_number, _label(later), later.effective_date),
        clauses=tuple(compared),
        removed=removed,
        changes={**changes, "removed": len(removed)},
    )
