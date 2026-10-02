"""Reading clauses out of the corpus.

Everything here resolves the version in force: the latest published version of a
document whose effective date has passed. A version published for a future date
is visible in the library but is not what a reader gets by default, and a draft
is never returned at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import (
    Document,
    DocumentNode,
    DocumentVersion,
    NodeReference,
    NodeText,
)


@dataclass(frozen=True)
class ClauseView:
    """One clause as a reader sees it."""

    key: str
    clause_type: str
    label: str | None
    heading: str | None
    text: str
    lang: str
    is_authoritative: bool
    is_normative: bool
    depth: int
    document_title: str
    document_slug: str
    version_label: str | None
    effective_date: date
    # Where the text came from, and how far it has been checked. Null for an
    # organisation's own policy, which is its own source and carries no tier.
    pack_slug: str | None = None
    jurisdiction: str | None = None
    trust_tier: str | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class ClauseDetail:
    """A clause with everything needed to read it in context."""

    clause: ClauseView
    breadcrumb: tuple[ClauseView, ...]
    children: tuple[ClauseView, ...]
    cross_references: tuple[tuple[str, str], ...]


class ClauseNotFound(Exception):
    """No clause with that key is in force."""


def _in_force(as_of: date) -> Select[tuple[DocumentVersion]]:
    """The published versions whose effective date has passed, latest per document."""
    return (
        select(DocumentVersion)
        .where(DocumentVersion.status == "published", DocumentVersion.effective_date <= as_of)
        .order_by(DocumentVersion.document_id, DocumentVersion.effective_date.desc())
    )


def _version_in_force(session: Session, document_id: object, as_of: date) -> DocumentVersion | None:
    return session.scalar(
        _in_force(as_of).where(DocumentVersion.document_id == document_id).limit(1)
    )


def _view(
    node: DocumentNode, text: NodeText, document: Document, version: DocumentVersion
) -> ClauseView:
    return ClauseView(
        key=node.canonical_key,
        clause_type=node.node_type,
        label=node.label,
        heading=text.heading,
        text=text.body_text,
        lang=text.lang,
        is_authoritative=text.is_authoritative,
        is_normative=node.is_normative,
        depth=node.depth,
        document_title=document.title,
        document_slug=document.slug,
        version_label=version.version_label,
        effective_date=version.effective_date,
        pack_slug=document.pack.slug if document.pack else None,
        jurisdiction=document.pack.jurisdiction if document.pack else None,
        trust_tier=document.pack.trust_tier if document.pack else None,
        source_url=document.pack.source_url if document.pack else None,
    )


def _text_for(session: Session, node: DocumentNode, lang: str | None) -> NodeText:
    query = select(NodeText).where(NodeText.node_id == node.id)
    if lang:
        requested = session.scalar(query.where(NodeText.lang == lang))
        if requested is not None:
            return requested

    # Fall back to the authoritative text, which is the one that prevails in law.
    found = session.scalars(query.order_by(NodeText.is_authoritative.desc())).first()
    if found is None:
        raise ClauseNotFound(f"{node.canonical_key} has no stored text")
    return found


@dataclass(frozen=True)
class _Located:
    """A clause found in the version of its document that is in force."""

    document: Document
    version: DocumentVersion
    node: DocumentNode


def _locate(session: Session, key: str, as_of: date) -> _Located:
    document_slug = key.split(":", 1)[0]

    document = session.scalar(select(Document).where(Document.slug == document_slug))
    if document is None:
        raise ClauseNotFound(f"no document with slug {document_slug!r}")

    version = _version_in_force(session, document.id, as_of)
    if version is None:
        raise ClauseNotFound(f"{document_slug} has no version in force on {as_of.isoformat()}")

    node = session.scalar(
        select(DocumentNode).where(
            DocumentNode.document_version_id == version.id,
            DocumentNode.canonical_key == key,
        )
    )
    if node is None:
        raise ClauseNotFound(f"{key} is not in {document_slug} as in force on {as_of.isoformat()}")

    return _Located(document=document, version=version, node=node)


def get_clause(
    session: Session, key: str, lang: str | None = None, as_of: date | None = None
) -> ClauseDetail:
    """One clause, with its breadcrumb, its children and the links its text states."""
    found = _locate(session, key, as_of or date.today())
    document, version, node = found.document, found.version, found.node

    return ClauseDetail(
        clause=_view(node, _text_for(session, node, lang), document, version),
        breadcrumb=_breadcrumb(session, node, document, version, lang),
        children=tuple(
            _view(child, _text_for(session, child, lang), document, version)
            for child in _children(session, node)
        ),
        cross_references=tuple(
            (reference.to_canonical_key, reference.raw_text)
            for reference in session.scalars(
                select(NodeReference)
                .where(NodeReference.node_id == node.id)
                .order_by(NodeReference.to_canonical_key)
            )
        ),
    )


def get_subtree(
    session: Session, key: str, lang: str | None = None, as_of: date | None = None
) -> list[ClauseView]:
    """A clause and everything beneath it, in reading order.

    Descendants come back in one query. Keys carry the hierarchy, so a prefix
    match finds them, and the parent links put them back in order.
    """
    located = _locate(session, key, as_of or date.today())
    document, version, root = located.document, located.version, located.node

    descendants = session.scalars(
        select(DocumentNode)
        .where(
            DocumentNode.document_version_id == version.id,
            DocumentNode.canonical_key.startswith(f"{key}:"),
        )
        .order_by(DocumentNode.order_index)
    )

    by_parent: dict[object, list[DocumentNode]] = {}
    for node in descendants:
        by_parent.setdefault(node.parent_node_id, []).append(node)

    found = [_view(root, _text_for(session, root, lang), document, version)]

    def walk(parent: DocumentNode) -> None:
        for child in by_parent.get(parent.id, []):
            found.append(_view(child, _text_for(session, child, lang), document, version))
            walk(child)

    walk(root)
    return found


def _children(session: Session, node: DocumentNode) -> list[DocumentNode]:
    return list(
        session.scalars(
            select(DocumentNode)
            .where(DocumentNode.parent_node_id == node.id)
            .order_by(DocumentNode.order_index)
        )
    )


def _breadcrumb(
    session: Session,
    node: DocumentNode,
    document: Document,
    version: DocumentVersion,
    lang: str | None,
) -> tuple[ClauseView, ...]:
    ancestors: list[ClauseView] = []
    current = node
    while current.parent_node_id is not None:
        parent = session.get(DocumentNode, current.parent_node_id)
        if parent is None:
            break
        ancestors.append(_view(parent, _text_for(session, parent, lang), document, version))
        current = parent
    return tuple(reversed(ancestors))


@dataclass(frozen=True)
class DocumentSummary:
    """One document as a list shows it, without any of its text."""

    slug: str
    title: str
    kind: str
    version_label: str | None
    effective_date: date
    clauses: int
    languages: tuple[str, ...]
    pack_slug: str | None
    jurisdiction: str | None
    trust_tier: str | None
    source_url: str | None


@dataclass(frozen=True)
class OutlineItem:
    """One top-level clause as an outline shows it: what it is, not what it says.

    The text is deliberately absent. An outline of the GDPR's articles would carry
    almost none anyway, because an article's words live in its paragraphs, but an
    outline of its recitals would carry all 173 of them in full, which is the
    context window problem this route exists to avoid.
    """

    key: str
    clause_type: str
    label: str | None
    heading: str | None
    is_normative: bool
    children: int
    """How many clauses sit directly beneath it, so a client knows whether to ask."""


@dataclass(frozen=True)
class DocumentDetail:
    """A document and the shape of it, rather than the whole of it.

    The outline is the top level only. Reading further is what a clause key and
    its subtree are for, because a document of a thousand clauses does not belong
    in one response.
    """

    summary: DocumentSummary
    outline: tuple[OutlineItem, ...]


def _summary(session: Session, document: Document, version: DocumentVersion) -> DocumentSummary:
    clauses = session.scalar(
        select(func.count())
        .select_from(DocumentNode)
        .where(DocumentNode.document_version_id == version.id)
    )
    languages = session.scalars(
        select(NodeText.lang)
        .join(DocumentNode, DocumentNode.id == NodeText.node_id)
        .where(DocumentNode.document_version_id == version.id)
        .distinct()
        .order_by(NodeText.lang)
    ).all()
    return DocumentSummary(
        slug=document.slug,
        title=document.title,
        kind=document.kind,
        version_label=version.version_label,
        effective_date=version.effective_date,
        clauses=int(clauses or 0),
        languages=tuple(languages),
        pack_slug=document.pack.slug if document.pack else None,
        jurisdiction=document.pack.jurisdiction if document.pack else None,
        trust_tier=document.pack.trust_tier if document.pack else None,
        source_url=document.pack.source_url if document.pack else None,
    )


def list_documents(
    session: Session, *, limit: int = 50, offset: int = 0, as_of: date | None = None
) -> tuple[list[DocumentSummary], int]:
    """The documents in force, and how many there are in total.

    A document with no published version in force is not listed: a corpus shows
    what can be cited today, and a draft cannot.
    """
    moment = as_of or date.today()
    documents = session.scalars(
        select(Document).where(Document.status == "active").order_by(Document.slug)
    ).all()

    summaries = [
        _summary(session, document, version)
        for document in documents
        if (version := _version_in_force(session, document.id, moment)) is not None
    ]
    return summaries[offset : offset + limit], len(summaries)


def get_document(session: Session, slug: str, *, as_of: date | None = None) -> DocumentDetail:
    """One document, with its top-level structure."""
    moment = as_of or date.today()
    document = session.scalar(select(Document).where(Document.slug == slug))
    if document is None:
        raise ClauseNotFound(f"no document with the slug {slug}")

    version = _version_in_force(session, document.id, moment)
    if version is None:
        raise ClauseNotFound(f"{slug} has no published version in force on {moment}")

    top = session.scalars(
        select(DocumentNode)
        .where(
            DocumentNode.document_version_id == version.id,
            DocumentNode.parent_node_id.is_(None),
        )
        .order_by(DocumentNode.order_index)
    ).all()

    return DocumentDetail(
        summary=_summary(session, document, version),
        outline=_outline(session, top),
    )


def _outline(session: Session, top: Sequence[DocumentNode]) -> tuple[OutlineItem, ...]:
    """Build the outline in two queries rather than two per clause."""
    ids = [node.id for node in top]
    if not ids:
        return ()

    headings: dict[uuid.UUID, str | None] = {}
    for row in session.execute(
        select(NodeText.node_id, NodeText.heading)
        .where(NodeText.node_id.in_(ids))
        .order_by(NodeText.is_authoritative.desc())
    ):
        headings.setdefault(row.node_id, row.heading)

    counts = {
        parent: total
        for parent, total in session.execute(
            select(DocumentNode.parent_node_id, func.count())
            .where(DocumentNode.parent_node_id.in_(ids))
            .group_by(DocumentNode.parent_node_id)
        )
    }

    return tuple(
        OutlineItem(
            key=node.canonical_key,
            clause_type=node.node_type,
            label=node.label,
            heading=headings.get(node.id),
            is_normative=node.is_normative,
            children=int(counts.get(node.id, 0)),
        )
        for node in top
    )
