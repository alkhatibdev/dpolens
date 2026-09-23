"""Reading clauses out of the corpus.

Everything here resolves the version in force: the latest published version of a
document whose effective date has passed. A version published for a future date
is visible in the library but is not what a reader gets by default, and a draft
is never returned at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, select
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
