"""Reading clauses out of the corpus.

Everything here resolves the version in force: the latest published version of a
document whose effective date has passed. A version published for a future date
is visible in the library but is not what a reader gets by default, and a draft
is never returned at all.

Within that version, each clause is read in the text that applies on the day asked
about. A clause that does not apply yet is read in the text it will start with, and
says so; a clause whose words an amendment changes later carries those words too.
A law is named in the language its text is read in.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
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
from dpolens.engine.packs.models import Pack


@dataclass(frozen=True)
class Coming:
    """The words an amendment gives a clause from a later day."""

    heading: str | None
    text: str
    in_force_from: date
    dates_set_by: str | None


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
    """In the language of the text, as a law's names are wherever its words are shown."""
    document_slug: str
    version_label: str | None
    effective_date: date
    in_force: bool = True
    """Whether this text applies on the day asked about."""
    in_force_from: date | None = None
    """The day this text starts to apply, or None while nothing has set it."""
    in_force_until: date | None = None
    """The day it stops applying, when a law or an amendment has set one."""
    dates_set_by: str | None = None
    """What set those days, when anything other than the version's effective date did."""
    coming: Coming | None = None
    """The words an amendment gives this clause later, when one does."""
    # Where the text came from, and how far it has been checked. Null for an
    # organisation's own policy, which is its own source and carries no tier.
    pack_slug: str | None = None
    law_short_name: str | None = None
    jurisdiction: str | None = None
    trust_tier: str | None = None
    source_url: str | None = None
    authoritative_language: str | None = None
    """Which language prevails where a law's texts disagree, so a translation can say so."""
    authoritative_text: str | None = None
    """The text that prevails, when this one is a translation, so the two can be read together."""
    archived: bool = False
    """The document no longer applies. Its clauses still read, and search no longer finds them."""


@dataclass(frozen=True)
class Continuation:
    """Where a rule read in an earlier version is in the version in force today."""

    key: str | None
    """Its key today, or None when the rule was removed."""

    version_label: str | None
    effective_date: date
    moved: bool
    changed: bool


@dataclass(frozen=True)
class Formerly:
    """The rule a policy's number named in an earlier version, before it named this one."""

    version_label: str | None
    heading: str | None
    text: str
    now: str | None
    """That rule's key in this version, or None when it was removed."""


@dataclass(frozen=True)
class ClauseDetail:
    """A clause with everything needed to read it in context."""

    clause: ClauseView
    breadcrumb: tuple[ClauseView, ...]
    children: tuple[ClauseView, ...]
    cross_references: tuple[tuple[str, str], ...]
    now: Continuation | None = None
    """Set when the version read is not the one in force: where the rule is today."""
    formerly: Formerly | None = None
    """Set when the key named a different rule in the version before."""


class ClauseNotFound(Exception):
    """No clause with that key is in force."""


def _in_force(as_of: date) -> Select[tuple[DocumentVersion]]:
    """The published versions whose effective date has passed, latest per document.

    A law pack corrected without the law changing keeps the law's date, so two
    versions can take effect on the same day: the later one is in force.
    """
    return (
        select(DocumentVersion)
        .where(DocumentVersion.status == "published", DocumentVersion.effective_date <= as_of)
        .order_by(
            DocumentVersion.document_id,
            DocumentVersion.effective_date.desc(),
            DocumentVersion.version_number.desc(),
        )
    )


def _version_in_force(session: Session, document_id: object, as_of: date) -> DocumentVersion | None:
    return session.scalar(
        _in_force(as_of).where(DocumentVersion.document_id == document_id).limit(1)
    )


def _view(
    node: DocumentNode,
    texts: _Texts,
    document: Document,
    version: DocumentVersion,
    as_of: date,
) -> ClauseView:
    text, prevailing = texts.shown, texts.prevailing
    names = document.pack.named_in(text.lang) if document.pack else None
    return ClauseView(
        key=node.canonical_key,
        clause_type=node.node_type,
        label=text.label or node.label,
        heading=text.heading,
        text=text.body_text,
        lang=text.lang,
        is_authoritative=text.is_authoritative,
        is_normative=node.is_normative,
        depth=node.depth,
        document_title=document.title_in(text.lang),
        document_slug=document.slug,
        version_label=version.version_label,
        effective_date=version.effective_date,
        in_force=_applies(text, as_of),
        in_force_from=None if text.pending else (text.applies_from or version.effective_date),
        in_force_until=text.applies_until,
        dates_set_by=text.dated_by,
        coming=(
            Coming(
                heading=texts.coming.heading,
                text=texts.coming.body_text,
                in_force_from=texts.coming.applies_from,
                dates_set_by=texts.coming.dated_by,
            )
            if texts.coming is not None and texts.coming.applies_from is not None
            else None
        ),
        pack_slug=document.pack.slug if document.pack else None,
        law_short_name=names.short_name if names else None,
        jurisdiction=names.jurisdiction if names else None,
        trust_tier=document.pack.trust_tier if document.pack else None,
        source_url=document.pack.source_url if document.pack else None,
        authoritative_language=document.pack.authoritative_language if document.pack else None,
        authoritative_text=prevailing.body_text if prevailing else None,
        archived=document.status == "archived",
    )


@dataclass(frozen=True)
class _Texts:
    shown: NodeText
    prevailing: NodeText | None
    """The text that prevails, when the one shown is a translation."""
    coming: NodeText | None
    """The words an amendment gives the clause later, in the language shown."""


def _applies(text: NodeText, as_of: date) -> bool:
    """Whether a text applies on `as_of`. One with no start applies from its version's date,
    which has passed for any version read."""
    return (
        not text.pending
        and (text.applies_from is None or text.applies_from <= as_of)
        and (text.applies_until is None or text.applies_until > as_of)
    )


def _ended(text: NodeText, as_of: date) -> bool:
    return text.applies_until is not None and text.applies_until <= as_of


def _on(texts: Sequence[NodeText], as_of: date) -> NodeText:
    """The text to read on `as_of`: the one that applies, else the one that applies next,
    else, for an old citation, the last that applied."""
    applying = [text for text in texts if _applies(text, as_of)]
    if applying:
        return max(applying, key=lambda text: text.applies_from or date.min)
    upcoming = [text for text in texts if not _ended(text, as_of)]
    if upcoming:
        return min(upcoming, key=lambda text: (text.pending, text.applies_from or date.max))
    return max(texts, key=lambda text: text.applies_until or date.min)


def _texts_for(session: Session, node: DocumentNode, lang: str | None, as_of: date) -> _Texts:
    """The text to show on `as_of`, in `lang` where the clause has it, the one that prevails
    when the shown one is a translation, and any words an amendment brings later. One query,
    since all may be needed."""
    texts = session.scalars(select(NodeText).where(NodeText.node_id == node.id)).all()
    if not texts:
        raise ClauseNotFound(f"{node.canonical_key} has no stored text")

    # The authoritative text prevails in law, and it is what a missing language falls back to.
    authoritative = [text for text in texts if text.is_authoritative] or list(texts)
    prevailing = _on(authoritative, as_of)
    in_lang = [text for text in texts if text.lang == lang] if lang else []
    shown = _on(in_lang, as_of) if in_lang else prevailing
    later = [
        text
        for text in texts
        if text.lang == shown.lang
        and text is not shown
        and text.applies_from is not None
        and text.applies_from > as_of
    ]
    return _Texts(
        shown=shown,
        prevailing=None if shown is prevailing else prevailing,
        coming=min(later, key=lambda text: text.applies_from or date.max) if later else None,
    )


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
    moment = as_of or date.today()
    found = _locate(session, key, moment)
    document, version, node = found.document, found.version, found.node
    policy = document.kind == "org_policy"

    return ClauseDetail(
        clause=_view(node, _texts_for(session, node, lang, moment), document, version, moment),
        breadcrumb=_breadcrumb(session, node, document, version, lang, moment),
        children=tuple(
            _view(child, _texts_for(session, child, lang, moment), document, version, moment)
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
        now=_continuation(session, document, version, node) if policy else None,
        formerly=_formerly(session, document, version, node) if policy else None,
    )


def _published(session: Session, document: Document) -> list[DocumentVersion]:
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document.id, DocumentVersion.status == "published"
            )
            .order_by(DocumentVersion.version_number)
        )
    )


def _successor(
    session: Session, node: DocumentNode, version: DocumentVersion
) -> DocumentNode | None:
    """The clause in `version` that continues `node`, matched when that version was drafted."""
    return session.scalar(
        select(DocumentNode).where(
            DocumentNode.previous_node_id == node.id,
            DocumentNode.document_version_id == version.id,
        )
    )


def _authoritative_text(session: Session, node: DocumentNode) -> NodeText | None:
    return session.scalar(
        select(NodeText).where(NodeText.node_id == node.id, NodeText.is_authoritative)
    )


def _continuation(
    session: Session, document: Document, version: DocumentVersion, node: DocumentNode
) -> Continuation | None:
    """Follow a rule from the version read to the one in force today, a version at a time."""
    today = _version_in_force(session, document.id, date.today())
    if today is None or today.id == version.id:
        return None
    later = [v for v in _published(session, document) if v.version_number > version.version_number]
    current: DocumentNode | None = node
    for step in later:
        if current is None:
            break
        current = _successor(session, current, step)
        if step.id == today.id:
            break
    if current is None:
        return Continuation(
            key=None,
            version_label=today.version_label,
            effective_date=today.effective_date,
            moved=False,
            changed=True,
        )
    before, after = _authoritative_text(session, node), _authoritative_text(session, current)
    changed = (
        (before.heading, before.body_text) != (after.heading, after.body_text)
        if (before and after)
        else True
    )
    return Continuation(
        key=current.canonical_key,
        version_label=today.version_label,
        effective_date=today.effective_date,
        moved=current.canonical_key != node.canonical_key,
        changed=changed,
    )


def _formerly(
    session: Session, document: Document, version: DocumentVersion, node: DocumentNode
) -> Formerly | None:
    """Whether this number named a different rule in the version before this one."""
    earlier = [
        v for v in _published(session, document) if v.version_number < version.version_number
    ]
    if not earlier:
        return None
    previous = earlier[-1]
    old = session.scalar(
        select(DocumentNode).where(
            DocumentNode.document_version_id == previous.id,
            DocumentNode.canonical_key == node.canonical_key,
        )
    )
    if old is None or old.id == node.previous_node_id:
        return None
    text = _authoritative_text(session, old)
    went = _successor(session, old, version)
    return Formerly(
        version_label=previous.version_label,
        heading=text.heading if text else None,
        text=text.body_text if text else "",
        now=went.canonical_key if went else None,
    )


def get_subtree(
    session: Session, key: str, lang: str | None = None, as_of: date | None = None
) -> list[ClauseView]:
    """A clause and everything beneath it, in reading order.

    Descendants come back in one query, found by their parent links rather than by their keys:
    a policy's 4.1 under 4 is keyed `slug:4.1`, not `slug:4:4.1`, because a number that
    continues its parent's stands alone.
    """
    moment = as_of or date.today()
    located = _locate(session, key, moment)
    document, version, root = located.document, located.version, located.node

    beneath = (
        select(DocumentNode.id)
        .where(DocumentNode.parent_node_id == root.id)
        .cte(name="beneath", recursive=True)
    )
    beneath = beneath.union_all(
        select(DocumentNode.id).where(DocumentNode.parent_node_id == beneath.c.id)
    )
    descendants = session.scalars(
        select(DocumentNode)
        .where(DocumentNode.id.in_(select(beneath.c.id)))
        .order_by(DocumentNode.order_index)
    )

    by_parent: dict[object, list[DocumentNode]] = {}
    for node in descendants:
        by_parent.setdefault(node.parent_node_id, []).append(node)

    found = [_view(root, _texts_for(session, root, lang, moment), document, version, moment)]

    def walk(parent: DocumentNode) -> None:
        for child in by_parent.get(parent.id, []):
            texts = _texts_for(session, child, lang, moment)
            found.append(_view(child, texts, document, version, moment))
            walk(child)

    walk(root)
    return found


def first_paragraph(
    session: Session, detail: ClauseDetail, as_of: date | None = None
) -> str | None:
    """The first paragraph of the article a clause sits in, when the clause is in a later one.

    An article made of numbered paragraphs states its rule in the first: Article 15(1) of the
    GDPR grants the right of access, and 15(3) and 15(4) say how the copy is given and what
    limits it. An article with words of its own before its paragraphs lists cases or duties
    instead, one in each paragraph, so none of them is its rule. That article, a clause in the
    first paragraph or in none, and a policy, whose sections follow no such convention, all
    get None.
    """
    if detail.clause.pack_slug is None:
        return None
    path = (*detail.breadcrumb, detail.clause)
    at = next((i for i, view in enumerate(path) if view.clause_type == "paragraph"), None)
    if at is None or at == 0:
        return None
    article, paragraph = path[at - 1], path[at]
    if article.text.strip():
        return None
    node = _locate(session, article.key, as_of or date.today()).node
    first = session.scalar(
        select(DocumentNode.canonical_key)
        .where(DocumentNode.parent_node_id == node.id, DocumentNode.node_type == "paragraph")
        .order_by(DocumentNode.order_index)
        .limit(1)
    )
    return first if first != paragraph.key else None


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
    as_of: date,
) -> tuple[ClauseView, ...]:
    ancestors: list[ClauseView] = []
    current = node
    while current.parent_node_id is not None:
        parent = session.get(DocumentNode, current.parent_node_id)
        if parent is None:
            break
        texts = _texts_for(session, parent, lang, as_of)
        ancestors.append(_view(parent, texts, document, version, as_of))
        current = parent
    return tuple(reversed(ancestors))


@dataclass(frozen=True)
class DocumentSummary:
    """One document as a list shows it, without any of its text.

    Names come in every language there is one for, and the reader picks: an English screen
    names a law in English, and one in the law's language would name it in that.
    """

    slug: str
    title: dict[str, str]
    kind: str
    version_label: str | None
    effective_date: date
    clauses: int
    languages: tuple[str, ...]
    pack_slug: str | None
    short_name: dict[str, str] | None
    """For a law, what people call it, such as GDPR."""
    jurisdiction: dict[str, str] | None
    trust_tier: str | None
    source_url: str | None
    authoritative_language: str | None = None
    """For a law, the language whose text prevails where its texts disagree."""


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
    pack = document.pack
    return DocumentSummary(
        slug=document.slug,
        title={title.lang: title.title for title in document.titles},
        kind=document.kind,
        version_label=version.version_label,
        effective_date=version.effective_date,
        clauses=int(clauses or 0),
        languages=tuple(languages),
        pack_slug=pack.slug if pack else None,
        short_name={names.lang: names.short_name for names in pack.names} if pack else None,
        jurisdiction={names.lang: names.jurisdiction for names in pack.names} if pack else None,
        trust_tier=document.pack.trust_tier if document.pack else None,
        source_url=document.pack.source_url if document.pack else None,
        authoritative_language=document.pack.authoritative_language if document.pack else None,
    )


def list_documents(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    as_of: date | None = None,
    laws: Collection[str] | None = None,
) -> tuple[list[DocumentSummary], int]:
    """The documents in force, and how many there are in total.

    A document with no published version in force is not listed: a corpus shows
    what can be cited today, and a draft cannot. `laws` keeps the laws listed to
    those packs, and the organisation's own policies are always listed.
    """
    moment = as_of or date.today()
    documents = session.scalars(
        select(Document).where(Document.status == "active").order_by(Document.slug)
    ).all()

    summaries = [
        _summary(session, document, version)
        for document in documents
        if (laws is None or document.pack is None or document.pack.slug in laws)
        and (version := _version_in_force(session, document.id, moment)) is not None
    ]
    return summaries[offset : offset + limit], len(summaries)


@dataclass(frozen=True)
class LawSummary:
    """A loaded law as somebody deciding whether it applies sees it, named in each language
    its pack names it in."""

    slug: str
    name: dict[str, str]
    short_name: dict[str, str]
    jurisdiction: dict[str, str]
    region: str | None
    version: str
    effective_date: date
    trust_tier: str
    authoritative_language: str
    languages: tuple[str, ...]
    articles: int
    recitals: int
    document: str | None
    """The document that holds its articles, which is the one to read."""


def list_laws(session: Session, *, as_of: date | None = None) -> list[LawSummary]:
    """Every loaded law by slug, counted as it stands in force."""
    moment = as_of or date.today()
    laws = []
    for pack in session.scalars(select(Pack).order_by(Pack.slug)).all():
        documents = session.scalars(
            select(Document)
            .where(Document.pack_id == pack.id, Document.status == "active")
            .order_by(Document.slug)
        ).all()
        versions = {
            document.slug: version
            for document in documents
            if (version := _version_in_force(session, document.id, moment)) is not None
        }
        ids = [version.id for version in versions.values()]
        counts: dict[tuple[uuid.UUID, str], int] = {}
        languages: Sequence[str] = ()
        if ids:
            for version_id, node_type, total in session.execute(
                select(DocumentNode.document_version_id, DocumentNode.node_type, func.count())
                .where(
                    DocumentNode.document_version_id.in_(ids),
                    DocumentNode.node_type.in_(("article", "recital")),
                )
                .group_by(DocumentNode.document_version_id, DocumentNode.node_type)
            ).tuples():
                counts[(version_id, node_type)] = total
            languages = session.scalars(
                select(NodeText.lang)
                .join(DocumentNode, DocumentNode.id == NodeText.node_id)
                .where(DocumentNode.document_version_id.in_(ids))
                .distinct()
                .order_by(NodeText.lang)
            ).all()

        articles = {
            slug: counts.get((version.id, "article"), 0) for slug, version in versions.items()
        }
        laws.append(
            LawSummary(
                slug=pack.slug,
                name={names.lang: names.name for names in pack.names},
                short_name={names.lang: names.short_name for names in pack.names},
                jurisdiction={names.lang: names.jurisdiction for names in pack.names},
                region=pack.region,
                version=pack.version,
                effective_date=pack.effective_date,
                trust_tier=pack.trust_tier,
                authoritative_language=pack.authoritative_language,
                languages=tuple(languages),
                articles=sum(articles.values()),
                recitals=sum(count for (_, kind), count in counts.items() if kind == "recital"),
                document=max(articles, key=articles.__getitem__, default=None),
            )
        )
    return laws


def get_document(
    session: Session, slug: str, *, as_of: date | None = None, lang: str | None = None
) -> DocumentDetail:
    """One document, with its top-level structure, named in `lang` where it can be."""
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
        outline=_outline(session, top, lang),
    )


def _outline(
    session: Session, top: Sequence[DocumentNode], lang: str | None = None
) -> tuple[OutlineItem, ...]:
    """Build the outline in two queries rather than two per clause.

    Each clause is named in `lang` where it has text in that language, and
    otherwise in the language that prevails, as a clause is when it is read.
    """
    ids = [node.id for node in top]
    if not ids:
        return ()

    names: dict[uuid.UUID, tuple[str | None, str | None]] = {}
    for row in session.execute(
        select(NodeText.node_id, NodeText.heading, NodeText.label)
        .where(NodeText.node_id.in_(ids))
        .order_by(
            (NodeText.lang == (lang or "")).desc(),
            NodeText.is_authoritative.desc(),
            # The words in force before any an amendment brings later.
            NodeText.applies_from.asc().nulls_first(),
        )
    ):
        names.setdefault(row.node_id, (row.heading, row.label))

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
            label=(names.get(node.id, (None, None))[1] or node.label),
            heading=names.get(node.id, (None, None))[0],
            is_normative=node.is_normative,
            children=int(counts.get(node.id, 0)),
        )
        for node in top
    )
