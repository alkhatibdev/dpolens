"""Loading a pack into the corpus.

A pack arrives as reviewed files and is stored, not parsed: the structure was
settled when the pack was built. Loading the same pack version twice is a no-op,
so a restart or a repeated command cannot duplicate a law.

A newer version is stored beside the one before it, and becomes the version in
force from its effective date. An older version than the one loaded is refused:
stored, it would read as the newest text of its day.

Each text is stored with the days it applies: the pack's effective date unless its
commencement says otherwise, and for words an amendment brings later, from that day,
with the words they replace ending the same day. A published version is never changed
once written, so the whole tree is put together first and written once.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import (
    Document,
    DocumentNode,
    DocumentTitle,
    DocumentVersion,
    NodeReference,
    NodeText,
)
from dpolens.engine.packs.format import (
    Clause,
    ComingText,
    CrossReference,
    Dates,
    PackDocument,
    PackFormatError,
    PackMetadata,
    read_coming,
    read_document,
    read_pack_metadata,
    read_translations,
)
from dpolens.engine.packs.models import Pack, PackName


@dataclass(frozen=True)
class LoadResult:
    pack_slug: str
    version: str
    documents_loaded: int
    clauses_loaded: int
    already_loaded: bool
    version_ids: tuple[uuid.UUID, ...] = field(default=())


class OlderPack(PackFormatError):
    """A pack version older than the one an instance has loaded."""


def loaded_version(session: Session, slug: str) -> str | None:
    """The version of a pack this instance has loaded, if any."""
    return session.scalar(select(Pack.version).where(Pack.slug == slug))


def loaded_packs(session: Session) -> dict[str, str]:
    """Every pack this instance has loaded, with its version."""
    return {slug: version for slug, version in session.execute(select(Pack.slug, Pack.version))}


def version_key(version: str) -> tuple[int, ...]:
    """A pack's version as numbers, so 2026.10 sorts after 2026.9."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as error:
        raise PackFormatError(f"{version!r} is not a pack version: write it as 2026.1") from error


def source_ref(pack: PackMetadata) -> str:
    return f"pack:{pack.slug}@{pack.version}"


def load_pack(session: Session, pack_dir: Path) -> LoadResult:
    """Read a pack directory and store every clause in it."""
    pack = read_pack_metadata(pack_dir)
    reference = source_ref(pack)
    loaded = loaded_version(session, pack.slug)
    if loaded is not None and version_key(pack.version) < version_key(loaded):
        raise OlderPack(
            f"this instance has {pack.slug} {loaded}, which is newer than {pack.version}"
        )
    row = _pack_row(session, pack)

    if _already_loaded(session, pack, reference):
        # The documents are here; their pack may not be, on an instance loaded
        # before this table existed. Linking them is what gives an old instance
        # its trust tier back.
        _link_documents(session, row, [entry.slug for entry in pack.documents])
        return LoadResult(pack.slug, pack.version, 0, 0, already_loaded=True)

    clauses_loaded = 0
    versions: list[uuid.UUID] = []
    for entry in pack.documents:
        clauses = read_document(pack_dir, entry)
        tree = _tree(
            pack,
            entry,
            clauses,
            read_translations(pack_dir, entry, pack, clauses),
            read_coming(pack_dir, entry, pack),
        )
        document = _document_for(session, pack, entry, row)
        version = _new_version(session, document, pack, reference)
        versions.append(version.id)
        clauses_loaded += _store(session, version, tree, parent=None, depth=0)

    return LoadResult(
        pack_slug=pack.slug,
        version=pack.version,
        documents_loaded=len(pack.documents),
        clauses_loaded=clauses_loaded,
        already_loaded=False,
        version_ids=tuple(versions),
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


def _pack_row(session: Session, pack: PackMetadata) -> Pack:
    """Store what the pack file says about itself, or refresh it.

    One row per slug, holding the version that is loaded. A newer pack version
    updates it in place, because a citation carries the document version it came
    from and this row only answers which law it is and how far it has been
    checked.
    """
    row = session.scalar(select(Pack).where(Pack.slug == pack.slug))
    if row is None:
        row = Pack(slug=pack.slug)
        session.add(row)

    row.region = pack.region
    _set_names(row, pack)
    row.version = pack.version
    row.effective_date = pack.effective_date
    row.trust_tier = pack.trust_tier
    row.source_url = pack.source_url
    row.license = pack.license
    row.authoritative_language = pack.authoritative_language
    session.flush()
    return row


def _set_names(row: Pack, pack: PackMetadata) -> None:
    """The law's names in each language, changed in place so a reload rewrites no key."""
    current = {names.lang: names for names in row.names}
    for lang in pack.name:
        names = current.pop(lang, None)
        if names is None:
            names = PackName(lang=lang)
            row.names.append(names)
        names.name = pack.name[lang]
        names.short_name = pack.short_name[lang]
        names.jurisdiction = pack.jurisdiction[lang]
    for gone in current.values():
        row.names.remove(gone)


def _set_titles(document: Document, entry: PackDocument) -> None:
    current = {title.lang: title for title in document.titles}
    for lang, text in entry.title.items():
        title = current.pop(lang, None)
        if title is None:
            document.titles.append(DocumentTitle(lang=lang, title=text))
        else:
            title.title = text
    for gone in current.values():
        document.titles.remove(gone)


def _link_documents(session: Session, row: Pack, slugs: list[str]) -> None:
    for document in session.scalars(select(Document).where(Document.slug.in_(slugs))).all():
        if document.pack_id is None:
            document.pack_id = row.id
    session.flush()


def _document_for(session: Session, pack: PackMetadata, entry: PackDocument, row: Pack) -> Document:
    document = session.scalar(select(Document).where(Document.slug == entry.slug))
    if document is None:
        document = Document(kind="law", slug=entry.slug, status="active", pack_id=row.id)
        session.add(document)
    elif document.kind != "law":
        raise PackFormatError(
            f"slug '{entry.slug}' already belongs to an organisation policy. Pack slugs are "
            "reserved so that a citation always says which text it came from"
        )
    else:
        document.pack_id = row.id
    _set_titles(document, entry)
    session.flush()
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


@dataclass
class _Text:
    lang: str
    is_authoritative: bool
    translation_status: str
    heading: str | None
    label: str | None
    body_text: str
    dates: Dates


@dataclass
class _Node:
    """A clause as it will be stored, with every text it holds over time."""

    key: str
    clause_type: str
    label: str | None
    normative: bool
    texts: list[_Text] = field(default_factory=list)
    references: list[CrossReference] = field(default_factory=list)
    children: list[_Node] = field(default_factory=list)

    def walk(self) -> list[_Node]:
        return [self, *(found for child in self.children for found in child.walk())]


def _tree(
    pack: PackMetadata,
    entry: PackDocument,
    clauses: list[Clause],
    translations: dict[str, list[Clause]],
    coming: list[ComingText],
) -> list[_Node]:
    """The document as it will be stored: the text in force, dated by its commencement, and
    each amendment's words beside the words they replace."""
    statuses = {t.lang: t.translation_status for t in pack.translations}
    top = [
        _node(
            clause,
            [aligned[order] for aligned in translations.values()],
            statuses,
            entry.dates_of,
        )
        for order, clause in enumerate(clauses)
    ]
    for amendment in sorted(coming, key=lambda text: text.starts):
        _amend(top, amendment, statuses, entry.dates_of)
    return top


def _node(
    clause: Clause,
    translated: list[Clause],
    statuses: dict[str, str],
    dates_of: Callable[[str], Dates],
) -> _Node:
    """One clause and everything beneath it, each dated by `dates_of` its key."""
    when = dates_of(clause.key)
    node = _Node(
        key=clause.key,
        clause_type=clause.clause_type,
        label=clause.label,
        normative=clause.normative,
        texts=[
            _Text(
                clause.lang, True, "original", clause.heading, clause.label, clause.body_text, when
            ),
            *(
                _Text(t.lang, False, statuses[t.lang], t.heading, t.label, t.body_text, when)
                for t in translated
            ),
        ],
        references=list(clause.cross_references),
    )
    node.children = [
        _node(child, [t.children[order] for t in translated], statuses, dates_of)
        for order, child in enumerate(clause.children)
    ]
    return node


def _amend(
    top: list[_Node],
    amendment: ComingText,
    statuses: dict[str, str],
    dates_of: Callable[[str], Dates],
) -> None:
    """Put an amendment's words beside the words they replace, which end the day it starts."""
    starts = amendment.starts

    def amended(key: str) -> Dates:
        # An amendment changes a provision's words, not the day it comes into force: one that
        # starts later, or has no day yet, keeps its own.
        own = dates_of(key)
        source = "; ".join(dict.fromkeys(filter(None, (own.source, amendment.source))))
        if own.pending:
            return Dates(pending=True, ends=own.ends, source=source)
        return Dates(starts=max(starts, own.starts or starts), ends=own.ends, source=source)

    coming = _node(amendment.clause, list(amendment.translations.values()), statuses, amended)
    existing = next((node for node in top if node.key == coming.key), None)
    if existing is None:
        top.insert(_place(top, coming.key), coming)
        return

    # The words the clause has end on the day the amendment starts. Words that would only have
    # started then or later, or had no day set, never apply at all, so they are not kept.
    for node in existing.walk():
        kept = []
        for text in node.texts:
            if text.dates.ends is not None and text.dates.ends <= starts:
                kept.append(text)
            elif not text.dates.pending and (
                text.dates.starts is None or text.dates.starts < starts
            ):
                text.dates = Dates(
                    starts=text.dates.starts,
                    ends=starts,
                    source="; ".join(
                        dict.fromkeys(filter(None, (text.dates.source, amendment.source)))
                    ),
                )
                kept.append(text)
        node.texts = kept
    _merge(existing, coming)
    _prune(existing)


def _prune(node: _Node) -> None:
    """Drop the clauses an amendment removes before they ever applied: no text, nothing beneath."""
    for child in node.children:
        _prune(child)
    node.children = [child for child in node.children if child.texts or child.children]


def _merge(existing: _Node, coming: _Node) -> None:
    """Add a coming clause's texts to the clause it replaces, and any clause it adds."""
    existing.texts.extend(coming.texts)
    known = {(reference.key, reference.text) for reference in existing.references}
    existing.references.extend(
        reference for reference in coming.references if (reference.key, reference.text) not in known
    )
    order = [child.key for child in coming.children]
    for position, child in enumerate(coming.children):
        match = next((node for node in existing.children if node.key == child.key), None)
        if match is not None:
            _merge(match, child)
            continue
        # A clause the amendment adds goes after the one it follows in the amended text.
        before = order[:position]
        at = max(
            (index + 1 for index, node in enumerate(existing.children) if node.key in before),
            default=0,
        )
        existing.children.insert(at, child)


NUMBER = re.compile(r"(\d+)")


def _place(top: list[_Node], key: str) -> int:
    """Where a clause an amendment adds sits among the others: after art-5, before art-6."""

    def order(segment: str) -> list[int | str]:
        return [int(part) if part.isdigit() else part for part in NUMBER.split(segment)]

    added = order(key.split(":")[-1])
    return next(
        (index for index, node in enumerate(top) if order(node.key.split(":")[-1]) > added),
        len(top),
    )


def _store(
    session: Session,
    version: DocumentVersion,
    nodes: list[_Node],
    parent: DocumentNode | None,
    depth: int,
) -> int:
    stored = 0
    for order, built in enumerate(nodes):
        node = DocumentNode(
            document_version_id=version.id,
            parent_node_id=parent.id if parent else None,
            canonical_key=built.key,
            node_type=built.clause_type,
            label=built.label,
            is_normative=built.normative,
            order_index=order,
            depth=depth,
        )
        session.add(node)
        session.flush()
        for text in built.texts:
            session.add(
                NodeText(
                    node_id=node.id,
                    lang=text.lang,
                    is_authoritative=text.is_authoritative,
                    translation_status=text.translation_status,
                    heading=text.heading,
                    label=text.label,
                    body_text=text.body_text,
                    applies_from=text.dates.starts,
                    applies_until=text.dates.ends,
                    pending=text.dates.pending,
                    dated_by=text.dates.source,
                )
            )
        for reference in built.references:
            session.add(
                NodeReference(
                    node_id=node.id, to_canonical_key=reference.key, raw_text=reference.text
                )
            )
        stored += 1 + _store(session, version, built.children, node, depth + 1)
    return stored
