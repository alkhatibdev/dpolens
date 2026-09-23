"""Loading a pack into the corpus.

A pack arrives as reviewed files and is stored, not parsed: the structure was
settled when the pack was built. Loading the same pack version twice is a no-op,
so a restart or a repeated command cannot duplicate a law.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import (
    Document,
    DocumentNode,
    DocumentVersion,
    NodeReference,
    NodeText,
)
from dpolens.engine.packs.format import (
    Clause,
    PackDocument,
    PackFormatError,
    PackMetadata,
    read_document,
    read_pack_metadata,
)


@dataclass(frozen=True)
class LoadResult:
    pack_slug: str
    version: str
    documents_loaded: int
    clauses_loaded: int
    already_loaded: bool


def source_ref(pack: PackMetadata) -> str:
    return f"pack:{pack.slug}@{pack.version}"


def load_pack(session: Session, pack_dir: Path) -> LoadResult:
    """Read a pack directory and store every clause in it."""
    pack = read_pack_metadata(pack_dir)
    reference = source_ref(pack)

    if _already_loaded(session, pack, reference):
        return LoadResult(pack.slug, pack.version, 0, 0, already_loaded=True)

    clauses_loaded = 0
    for entry in pack.documents:
        clauses = read_document(pack_dir, entry)
        document = _document_for(session, pack, entry)
        version = _new_version(session, document, pack, reference)
        clauses_loaded += _store_clauses(session, version, clauses, pack)

    return LoadResult(
        pack_slug=pack.slug,
        version=pack.version,
        documents_loaded=len(pack.documents),
        clauses_loaded=clauses_loaded,
        already_loaded=False,
    )


def _already_loaded(session: Session, pack: PackMetadata, reference: str) -> bool:
    slugs = [entry.slug for entry in pack.documents]
    existing = session.scalar(
        select(DocumentVersion)
        .join(Document)
        .where(Document.slug.in_(slugs), DocumentVersion.source_ref == reference)
        .limit(1)
    )
    return existing is not None


def _document_for(session: Session, pack: PackMetadata, entry: PackDocument) -> Document:
    document = session.scalar(select(Document).where(Document.slug == entry.slug))
    if document is None:
        document = Document(kind="law", slug=entry.slug, title=entry.title, status="active")
        session.add(document)
        session.flush()
    elif document.kind != "law":
        raise PackFormatError(
            f"slug '{entry.slug}' already belongs to an organisation policy. Pack slugs are "
            "reserved so that a citation always says which text it came from"
        )
    return document


def _new_version(
    session: Session, document: Document, pack: PackMetadata, reference: str
) -> DocumentVersion:
    previous = session.scalars(
        select(DocumentVersion.version_number).where(DocumentVersion.document_id == document.id)
    ).all()
    version = DocumentVersion(
        document_id=document.id,
        version_number=max(previous, default=0) + 1,
        version_label=pack.version,
        status="published",
        effective_date=pack.effective_date,
        source_ref=reference,
        published_at=datetime.now(UTC),
    )
    session.add(version)
    session.flush()
    return version


def _store_clauses(
    session: Session, version: DocumentVersion, clauses: list[Clause], pack: PackMetadata
) -> int:
    stored = 0
    for order, clause in enumerate(clauses):
        stored += _store_clause(session, version, clause, pack, parent=None, order=order, depth=0)
    return stored


def _store_clause(
    session: Session,
    version: DocumentVersion,
    clause: Clause,
    pack: PackMetadata,
    parent: DocumentNode | None,
    order: int,
    depth: int,
) -> int:
    node = DocumentNode(
        document_version_id=version.id,
        parent_node_id=parent.id if parent else None,
        canonical_key=clause.key,
        node_type=clause.clause_type,
        label=clause.label,
        is_normative=clause.normative,
        order_index=order,
        depth=depth,
    )
    session.add(node)
    session.flush()

    is_authoritative = clause.lang == pack.authoritative_language
    session.add(
        NodeText(
            node_id=node.id,
            lang=clause.lang,
            is_authoritative=is_authoritative,
            translation_status="original" if is_authoritative else "official_translation",
            heading=clause.heading,
            body_text=clause.body_text,
        )
    )
    for reference in clause.cross_references:
        session.add(
            NodeReference(node_id=node.id, to_canonical_key=reference.key, raw_text=reference.text)
        )

    stored = 1
    for child_order, child in enumerate(clause.children):
        stored += _store_clause(session, version, child, pack, node, child_order, depth + 1)
    return stored
