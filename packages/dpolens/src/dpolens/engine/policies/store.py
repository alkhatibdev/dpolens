"""Policies in the database: drafts from uploads, then published, discarded or archived.

An upload is parsed in the request that brings it. Parsing takes well under a second, and doing
it there means an unreadable, empty or unsupported file is refused at once, with what to do,
instead of becoming a draft that fails later. The original file is stored first, then the draft
version, its clauses and its flags. Publishing needs every flag accepted, makes the version
immutable, and queues the job that embeds it. Every step is written to the governance log.

A new version of a policy is matched to the version before it (`versions.py`): each clause says
which earlier clause it continues and how it changed, and a renumbered clause is a flag.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePath
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import User
from dpolens.engine.documents.models import (
    Document,
    DocumentNode,
    DocumentVersion,
    NodeText,
    ParseFlag,
)
from dpolens.engine.jobs import job_status, queue_indexing
from dpolens.engine.logs.governance import (
    DOCUMENT_ARCHIVED,
    DOCUMENT_CLAUSE_FIXED,
    DOCUMENT_DRAFT_DISCARDED,
    DOCUMENT_DRAFT_EDITED,
    DOCUMENT_DRAFTED,
    DOCUMENT_FLAG_ACCEPTED,
    DOCUMENT_MATCH_REJECTED,
    DOCUMENT_PUBLISHED,
    Actor,
    record,
)
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.originals import Originals, Stored
from dpolens.engine.policies.blocks import UnreadablePolicy
from dpolens.engine.policies.checks import check_keys, check_numbering, snippet
from dpolens.engine.policies.fixing import (
    DONE,
    CannotFix,
    Part,
    Result,
    apply,
    boundaries,
    fixes,
    keyed,
    locate,
    opening_number,
    possible,
)
from dpolens.engine.policies.fixing import walk as walk_parts
from dpolens.engine.policies.keys import slug_of
from dpolens.engine.policies.parse import parse_policy, read_file
from dpolens.engine.policies.patterns import parse_label
from dpolens.engine.policies.reading import Line, as_rows, from_rows, lines_of
from dpolens.engine.policies.tree import Clause, Edit, Flag, Layer, ParsedPolicy
from dpolens.engine.policies.versions import (
    MOVED_SIMILARITY,
    Change,
    Earlier,
    Later,
    Match,
    Matching,
    match,
    reused,
    similarity,
    words,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
MAX_KEY = 200
SAMPLE = Path(__file__).with_name("sample-policy.md")
SAMPLE_SLUG = "sample-data-protection"
SAMPLE_EFFECTIVE = date(2026, 1, 1)
DOCUMENT_ACTIONS = (
    DOCUMENT_DRAFTED,
    DOCUMENT_FLAG_ACCEPTED,
    DOCUMENT_DRAFT_EDITED,
    DOCUMENT_MATCH_REJECTED,
    DOCUMENT_CLAUSE_FIXED,
    DOCUMENT_PUBLISHED,
    DOCUMENT_DRAFT_DISCARDED,
    DOCUMENT_ARCHIVED,
)
MATCH_REJECTED = "match-rejected"


class PolicyNotFound(Exception):
    """No organisation policy has that slug."""


class PolicyExists(Exception):
    """A document already has that slug."""


class DraftExists(Exception):
    """The policy has a draft already; one at a time."""

    def __init__(self, slug: str, version: int) -> None:
        super().__init__(
            f"{slug} already has a draft (version {version}). Discard it, or replace it with "
            "this upload."
        )
        self.slug = slug
        self.version = version


class NoDraft(Exception):
    """The policy has no draft to read, edit, publish or discard."""


class FlagsOpen(Exception):
    """A draft cannot be published while a flag is neither resolved nor accepted."""

    def __init__(self, slug: str, positions: list[int]) -> None:
        listed = ", ".join(str(position) for position in positions)
        super().__init__(
            f"{slug} has {len(positions)} flag{'s' if len(positions) > 1 else ''} to settle "
            f"before it can be published: {listed}."
        )
        self.positions = positions


class FlagNotFound(Exception):
    """The draft has no flag in that place."""


class NoClause(Exception):
    """The draft has no clause by that key."""


class NoMatch(Exception):
    """The draft has no clause by that key that continues one of the version before."""


class StaleDraft(Exception):
    """The draft changed after the caller read it, so their change could undo somebody else's."""

    def __init__(
        self, slug: str, revision: int, updated_at: datetime | None, updated_by: str | None
    ) -> None:
        super().__init__(f"{slug}'s draft changed after it was read: it is at revision {revision}.")
        self.revision = revision
        self.updated_at = updated_at
        self.updated_by = updated_by


class EffectiveDateTooEarly(Exception):
    """Versions take effect in the order they are published, so that the version a citation
    names and the version in force on a given day always agree."""


class LabelTaken(Exception):
    """Another version of the policy has that label, and a citation names its version by it."""


class BadSlug(Exception):
    """A slug is lower-case Latin letters, digits and hyphens."""


@dataclass(frozen=True)
class FlagSuggestion:
    """The fix the parser would make, while it can still be made."""

    edit: Edit
    key: str
    """The clause it applies to."""

    at: int | None
    """For a split, where in that clause's text the second part begins."""


@dataclass(frozen=True)
class FlagView:
    position: int
    kind: str
    key: str | None
    detail: str
    accepted_by: str | None
    """Who accepted it: a person's name, or "the command line"."""

    accepted_at: datetime | None
    resolved_by: str | None
    """Who made the change that settled it, named as `accepted_by` is."""

    resolved_at: datetime | None
    resolution: str | None
    paragraph: int | None
    resolution_key: str | None = None
    """The clause the change that settled it named: what it went under or into, or a split's
    second part."""

    suggestion: FlagSuggestion | None = None


@dataclass(frozen=True)
class EarlierClause:
    """The clause a new one continues, as the version before has it."""

    key: str
    label: str | None
    heading: str | None
    text: str


@dataclass(frozen=True)
class DraftClause:
    key: str
    kind: str
    label: str | None
    heading: str | None
    text: str
    lang: str
    layer: str | None
    change: str | None
    """added, modified, moved or unchanged against the previous version; empty for the first."""

    continues: str | None
    """The key of the clause it continues in the previous version."""

    earlier: EarlierClause | None
    """That clause's words, when this one is renumbered or reworded."""

    children: tuple[DraftClause, ...]
    fixed: str | None = None
    """What a reviewer last did to where it begins or how deep it sits."""

    fixes: tuple[Edit, ...] = ()
    """The fixes that can be made to it where it sits, while it is a draft."""

    splits: tuple[tuple[int, str | None], ...] = ()
    """Where in its text it can be split, each with the number the second part would take."""


@dataclass(frozen=True)
class VersionView:
    slug: str
    title: str
    number: int
    label: str | None
    status: str
    effective_date: date
    source_name: str | None
    source_format: str | None
    source_size: int | None
    created_at: datetime
    created_by: str | None
    published_at: datetime | None
    published_by: str | None
    indexing: str | None
    """The embedding job's status once published: todo, doing, succeeded or failed."""


@dataclass(frozen=True)
class DraftView:
    version: VersionView
    clauses: tuple[DraftClause, ...]
    flags: tuple[FlagView, ...]
    checks: dict[str, Any]
    previous: str | None
    """The label of the version this draft was matched to, if there is one."""

    removed: tuple[dict[str, str | None], ...]
    changes: dict[str, int]
    revision: int
    updated_at: datetime | None
    updated_by: str | None
    next_label: str
    """The label it is published with, which is how citations will name it."""


@dataclass(frozen=True)
class Scheduled:
    """A published version that takes effect later."""

    label: str
    effective_date: date


@dataclass(frozen=True)
class DraftReview:
    """How far a draft's review has got."""

    flags: int
    open: int
    uploaded_by: str | None
    uploaded_at: datetime
    next_label: str


@dataclass(frozen=True)
class LastChange:
    by: str | None
    """A person's name; empty for a change made on the command line."""

    at: datetime


@dataclass(frozen=True)
class PolicySummary:
    slug: str
    title: str
    status: str
    in_force: str | None
    in_force_since: date | None
    published: int
    draft: int | None
    indexing: str | None
    """The latest published version's embedding job: todo, doing, succeeded or failed."""

    in_force_number: int | None
    """The number of the version in force, which names its original file."""

    next_label: str
    """The label a new version is published with, unless it is given one."""

    sample: bool
    scheduled: Scheduled | None
    review: DraftReview | None
    last_change: LastChange | None


@dataclass(frozen=True)
class FileLine:
    """A paragraph of the file, with the clause it went to or why it was set aside."""

    line: Line
    clause: str | None
    set_aside: str | None
    clauses: tuple[str, ...] = ()
    """Every clause that holds part of it: two, once a clause is split inside it."""


@dataclass(frozen=True)
class FixedDraft:
    """A draft after a reviewer fixed how one of its clauses was read."""

    draft: DraftView
    clause: str
    """The key the clause has now: its own, or for a merge the clause it went into."""


@dataclass(frozen=True)
class FileView:
    slug: str
    number: int
    status: str
    name: str | None
    format: str | None
    size: int | None
    lines: tuple[FileLine, ...]


def _check_slug(slug: str) -> None:
    if not SLUG.match(slug):
        raise BadSlug(
            f"{slug!r} cannot be a policy's slug. Use lower-case Latin letters, digits and "
            "hyphens, such as data-protection."
        )


def _document(session: Session, slug: str) -> Document:
    found = session.scalars(
        select(Document).where(Document.slug == slug, Document.kind == "org_policy")
    ).first()
    if found is None:
        raise PolicyNotFound(f"There is no policy called {slug}.")
    return found


def _draft_of(
    session: Session, document: Document, *, lock: bool = False
) -> DocumentVersion | None:
    query = select(DocumentVersion).where(
        DocumentVersion.document_id == document.id, DocumentVersion.status == "draft"
    )
    if lock:
        # Held until the change commits, so two changes made at once take turns and the second
        # sees the revision the first left.
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def _require_draft(
    session: Session,
    document: Document,
    *,
    lock: bool = False,
    expected_revision: int | None = None,
) -> DocumentVersion:
    """The draft, refused if it changed since the revision the caller read, when they name one."""
    draft = _draft_of(session, document, lock=lock)
    if draft is None:
        raise NoDraft(f"{document.slug} has no draft.")
    if expected_revision is not None and draft.revision != expected_revision:
        names = _names(session, [draft.updated_by_user_id])
        raise StaleDraft(
            document.slug,
            draft.revision,
            draft.updated_at,
            names.get(draft.updated_by_user_id) if draft.updated_by_user_id else None,
        )
    return draft


def _published_labels(session: Session, document: Document) -> set[str | None]:
    return set(
        session.scalars(
            select(DocumentVersion.version_label).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.status == "published",
            )
        )
    )


def _next_label(labels: set[str | None]) -> str:
    """The next number no published version of the policy has as its label."""
    number = len(labels) + 1
    while str(number) in labels:
        number += 1
    return str(number)


def _label_for(draft: DocumentVersion, labels: set[str | None]) -> str:
    """The label a draft is published with: the one it was given, or the next number free."""
    return draft.version_label or _next_label(labels)


def _changed(draft: DocumentVersion, actor: Actor) -> None:
    draft.revision += 1
    draft.updated_at = datetime.now(UTC)
    draft.updated_by_user_id = actor.user_id


def _latest_published(session: Session, document: Document) -> DocumentVersion | None:
    return session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id, DocumentVersion.status == "published")
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    ).first()


def _parse(data: bytes, filename: str, slug: str) -> ParsedPolicy:
    if len(data) > MAX_UPLOAD_BYTES:
        raise UnreadablePolicy("This file is larger than 25 MB, which no policy needs to be.")
    return parse_policy(data, filename, slug)


def upload_policy(
    session: Session,
    originals: Originals,
    data: bytes,
    filename: str,
    *,
    actor: Actor,
    slug: str | None = None,
    title: str | None = None,
    effective_date: date | None = None,
    version_label: str | None = None,
) -> DraftView:
    """A new policy: its document, and its first version as a draft."""
    slug = slug or slug_of(PurePath(filename).stem)
    _check_slug(slug)
    taken = session.scalars(select(Document.id).where(Document.slug == slug)).first()
    if taken is not None:
        raise PolicyExists(
            f"A document called {slug} exists already. Upload a new version of it, or choose "
            "another slug."
        )
    parsed = _parse(data, filename, slug)
    stored = originals.put(data)
    document = Document(
        kind="org_policy",
        slug=slug,
        title=title or parsed.title or PurePath(filename).stem.replace("-", " ").strip(),
        status="active",
    )
    session.add(document)
    session.flush()
    version = _write_draft(
        session, document, parsed, stored, filename, effective_date, version_label, actor, None
    )
    return read_draft(session, document.slug, version=version)


def upload_version(
    session: Session,
    originals: Originals,
    slug: str,
    data: bytes,
    filename: str,
    *,
    actor: Actor,
    effective_date: date | None = None,
    version_label: str | None = None,
    replace: bool = False,
) -> DraftView:
    """A new version of a policy, as a draft matched to the version before it."""
    document = _document(session, slug)
    existing = _draft_of(session, document, lock=True)
    if existing is not None and not replace:
        raise DraftExists(slug, existing.version_number)
    parsed = _parse(data, filename, slug)
    stored = originals.put(data)
    if existing is not None:
        _discard(session, document, existing, actor, reason="replaced by a new upload")
        session.flush()
    previous = _latest_published(session, document)
    version = _write_draft(
        session, document, parsed, stored, filename, effective_date, version_label, actor, previous
    )
    return read_draft(session, slug, version=version)


def _earlier(session: Session, version: DocumentVersion) -> list[Earlier]:
    # In a fixed order, so that matching the same file again pairs identical clauses the same way.
    rows = session.execute(
        select(DocumentNode, NodeText)
        .join(NodeText, NodeText.node_id == DocumentNode.id)
        .where(DocumentNode.document_version_id == version.id, NodeText.is_authoritative)
        .order_by(DocumentNode.depth, DocumentNode.order_index, DocumentNode.canonical_key)
    ).all()
    return [
        Earlier(
            id=node.id,
            key=node.canonical_key,
            label=node.label,
            heading=text.heading,
            text=text.body_text,
        )
        for node, text in rows
    ]


def _short(key: str, slug: str) -> str:
    return key.removeprefix(slug + ":")


def _matching_flags(
    matching: Matching,
    later: dict[str, Later],
    slug: str,
    label: str,
    quiet: frozenset[str] = frozenset(),
) -> list[Flag]:
    """One flag for each clause whose match a reviewer should check: renumbered, reworded too
    far to be sure it is the same rule, or holding a number that named a different rule in the
    version before. A clause in `quiet` was renumbered by a reviewer's own change, which needs
    no one to confirm it is the same rule when its words are."""
    flags: list[Flag] = []
    for key, found in matching.matches.items():
        said: list[str] = []
        if (
            found.change == "modified"
            and found.earlier is not None
            and found.score < MOVED_SIMILARITY
        ):
            old = found.earlier.heading or found.earlier.text
            said.append(
                f"{_short(key, slug)} has new words since version {label}, where it read: "
                f"{snippet(old, 80)} Check that it is still the same rule."
            )
        if found.change == "moved" and found.earlier is not None:
            clause = later[key]
            same = (clause.heading, clause.text) == (found.earlier.heading, found.earlier.text)
            how = "renumbered" if same else "renumbered and reworded"
            if not (same and key in quiet):
                said.append(
                    f"{_short(key, slug)} continues {_short(found.earlier.key, slug)} from "
                    f"version {label}, {how}. Check that it is the same rule."
                )
        if key in matching.reused:
            named, went = matching.reused[key]
            what = snippet(named.heading or named.text, 60)
            now = f"now {_short(went, slug)}" if went else "since removed"
            said.append(
                f"In version {label}, {_short(key, slug)} was a different rule ({what}), {now}."
            )
        if said:
            flags.append(Flag(kind="unmatched_key", detail=" ".join(said), key=key))
    return flags


def _stored(flag: Flag, rows: dict[str, uuid.UUID]) -> dict[str, Any] | None:
    """A flag's suggested fix as it is kept: the clause it applies to by its row, which stays
    the same however its key changes, and none when that clause is not there."""
    found = flag.suggestion
    if found is None:
        return None
    target = rows.get(found.key) if found.key else None
    if found.key and target is None:
        return None
    return {
        "edit": found.edit,
        "node": str(target) if target else None,
        "at": found.at,
        "label": found.label,
    }


def _write_draft(
    session: Session,
    document: Document,
    parsed: ParsedPolicy,
    stored: Stored,
    filename: str,
    effective_date: date | None,
    version_label: str | None,
    actor: Actor,
    previous: DocumentVersion | None,
) -> DocumentVersion:
    for clause in parsed.walk():
        if len(clause.key) > MAX_KEY:
            raise UnreadablePolicy(
                f"A clause's key would be longer than {MAX_KEY} characters ({clause.key[:60]}…). "
                "The document nests its headings too deeply."
            )
    numbers = session.scalars(
        select(DocumentVersion.version_number).where(DocumentVersion.document_id == document.id)
    ).all()
    matching: Matching | None = None
    previous_label: str | None = None
    later = {c.key: Later(c.key, c.label, c.heading, c.text) for c in parsed.walk()}
    if previous is not None:
        previous_label = previous.version_label or str(previous.version_number)
        matching = match(_earlier(session, previous), list(later.values()))
    version = DocumentVersion(
        document_id=document.id,
        version_number=max(numbers, default=0) + 1,
        version_label=version_label,
        status="draft",
        effective_date=effective_date or date.today(),
        source_ref=f"upload:{uuid.uuid4()}",
        source_key=stored.key,
        source_name=PurePath(filename).name,
        source_size=stored.size,
        source_sha256=stored.sha256,
        source_format=parsed.format,
        reading=as_rows(parsed.lines),
        updated_at=datetime.now(UTC),
        updated_by_user_id=actor.user_id,
        parse_checks={
            "coverage": asdict(parsed.coverage),
            "set_aside": [asdict(block) for block in parsed.set_aside],
            "notices": list(parsed.notices),
            "previous": previous_label,
            "removed": [
                {"key": gone.key, "heading": gone.heading, "text": gone.text}
                for gone in (matching.removed if matching else [])
            ],
        },
        created_by_user_id=actor.user_id,
    )
    session.add(version)
    session.flush()

    nodes: dict[str, DocumentNode] = {}

    def store(clause: Clause, parent: DocumentNode | None, order: int, depth: int) -> None:
        found = matching.matches.get(clause.key) if matching else None
        node = DocumentNode(
            document_version_id=version.id,
            parent_node_id=parent.id if parent else None,
            canonical_key=clause.key,
            node_type=clause.kind,
            label=clause.label,
            is_normative=True,
            order_index=order,
            depth=depth,
            parse_layer=clause.layer,
            source_anchor={"positions": list(clause.positions)},
            previous_node_id=found.earlier.id if found and found.earlier else None,
            change_type=found.change if found else None,
        )
        session.add(node)
        session.flush()
        nodes[clause.key] = node
        session.add(
            NodeText(
                node_id=node.id,
                lang=clause.lang,
                is_authoritative=True,
                translation_status="original",
                heading=clause.heading,
                label=clause.label,
                body_text=clause.text,
            )
        )
        for index, child in enumerate(clause.children):
            store(child, node, index, depth + 1)

    for index, clause in enumerate(parsed.clauses):
        store(clause, None, index, 0)

    flags = list(parsed.flags)
    if matching is not None and previous_label is not None:
        # In the order the clauses come, which is the order a reviewer reads them.
        order = {clause.key: index for index, clause in enumerate(parsed.walk())}
        found = _matching_flags(matching, later, document.slug, previous_label)
        flags.extend(sorted(found, key=lambda flag: order.get(flag.key or "", len(order))))
    for position, flag in enumerate(flags, start=1):
        node = nodes.get(flag.key) if flag.key else None
        session.add(
            ParseFlag(
                document_version_id=version.id,
                node_id=node.id if node else None,
                canonical_key=flag.key,
                kind=flag.kind,
                detail=flag.detail,
                position=position,
                paragraph=flag.position,
                suggestion=_stored(flag, {key: found.id for key, found in nodes.items()}),
            )
        )
    session.flush()
    record(
        session,
        actor=actor,
        action=DOCUMENT_DRAFTED,
        target_type="document_version",
        target_id=str(version.id),
        details={
            "document": document.slug,
            "title": document.title,
            "version": version.version_number,
            "file": version.source_name,
            "sha256": stored.sha256,
            "clauses": len(nodes),
            "flags": len(flags),
        },
    )
    return version


def _names(session: Session, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {found for found in ids if found is not None}
    if not wanted:
        return {}
    return dict(
        session.execute(select(User.id, User.display_name).where(User.id.in_(wanted)))
        .tuples()
        .all()
    )


def _version_view(session: Session, document: Document, version: DocumentVersion) -> VersionView:
    names = _names(session, [version.created_by_user_id, version.published_by_user_id])
    indexing = None
    if version.status == "published" and version.index_job_id is not None:
        indexing = job_status(session, version.index_job_id) or "succeeded"
    return VersionView(
        slug=document.slug,
        title=document.title,
        number=version.version_number,
        label=version.version_label,
        status=version.status,
        effective_date=version.effective_date,
        source_name=version.source_name,
        source_format=version.source_format,
        source_size=version.source_size,
        created_at=version.created_at,
        created_by=names.get(version.created_by_user_id) if version.created_by_user_id else None,
        published_at=version.published_at,
        published_by=(
            names.get(version.published_by_user_id) if version.published_by_user_id else None
        ),
        indexing=indexing,
    )


def read_draft(session: Session, slug: str, version: DocumentVersion | None = None) -> DraftView:
    """A draft as a reviewer reads it: its clauses, its flags, and what changed."""
    document = _document(session, slug)
    version = version or _require_draft(session, document)
    rows = session.execute(
        select(DocumentNode, NodeText)
        .join(NodeText, NodeText.node_id == DocumentNode.id)
        .where(DocumentNode.document_version_id == version.id, NodeText.is_authoritative)
        .order_by(DocumentNode.depth, DocumentNode.order_index)
    ).all()
    earlier = {
        node.id: EarlierClause(
            key=node.canonical_key, label=node.label, heading=text.heading, text=text.body_text
        )
        for node, text in session.execute(
            select(DocumentNode, NodeText)
            .join(NodeText, NodeText.node_id == DocumentNode.id)
            .where(
                DocumentNode.id.in_(
                    [node.previous_node_id for node, _ in rows if node.previous_node_id]
                ),
                NodeText.is_authoritative,
            )
        ).all()
    }
    children: dict[uuid.UUID | None, list[tuple[DocumentNode, NodeText]]] = {}
    for node, text in rows:
        children.setdefault(node.parent_node_id, []).append((node, text))
    roots = _parts_of([(node, text) for node, text in rows]) if version.status == "draft" else []
    offered = fixes(roots)

    def clause(node: DocumentNode, text: NodeText) -> DraftClause:
        before = earlier.get(node.previous_node_id) if node.previous_node_id else None
        can = tuple(offered.get(node.canonical_key, ()))
        return DraftClause(
            key=node.canonical_key,
            kind=node.node_type,
            label=node.label,
            heading=text.heading,
            text=text.body_text,
            lang=text.lang,
            layer=node.parse_layer,
            change=node.change_type,
            continues=before.key if before else None,
            earlier=before if node.change_type in ("modified", "moved") else None,
            children=build(node.id),
            fixed=node.fixed,
            fixes=can,
            splits=_splits(text.body_text) if "split" in can else (),
        )

    def build(parent: uuid.UUID | None) -> tuple[DraftClause, ...]:
        found = sorted(children.get(parent, []), key=lambda pair: pair[0].order_index)
        return tuple(clause(node, text) for node, text in found)

    flags = session.scalars(
        select(ParseFlag)
        .where(ParseFlag.document_version_id == version.id)
        .order_by(ParseFlag.position)
    ).all()
    names = _names(
        session,
        [
            version.updated_by_user_id,
            *(flag.accepted_by_user_id for flag in flags),
            *(flag.resolved_by_user_id for flag in flags),
        ],
    )

    def who(user: uuid.UUID | None, when: datetime | None) -> str | None:
        if user is not None:
            return names.get(user)
        return "the command line" if when else None

    suggest = _suggestions(roots, flags)
    flag_views = tuple(
        FlagView(
            position=flag.position,
            kind=flag.kind,
            key=flag.canonical_key,
            detail=flag.detail,
            accepted_by=who(flag.accepted_by_user_id, flag.accepted_at),
            accepted_at=flag.accepted_at,
            resolved_by=who(flag.resolved_by_user_id, flag.resolved_at),
            resolved_at=flag.resolved_at,
            resolution=flag.resolution,
            paragraph=flag.paragraph,
            resolution_key=flag.resolution_key,
            suggestion=suggest.get(flag.position),
        )
        for flag in flags
    )
    checks: dict[str, Any] = dict(version.parse_checks or {})
    removed = tuple(checks.get("removed") or ())
    changes = {"added": 0, "modified": 0, "moved": 0, "unchanged": 0}
    for node, _ in rows:
        if node.change_type in changes:
            changes[node.change_type] += 1
    changes["removed"] = len(removed)
    return DraftView(
        version=_version_view(session, document, version),
        clauses=build(None),
        flags=flag_views,
        checks=checks,
        previous=checks.get("previous"),
        removed=removed,
        changes=changes,
        revision=version.revision,
        updated_at=version.updated_at,
        updated_by=(names.get(version.updated_by_user_id) if version.updated_by_user_id else None),
        next_label=_label_for(version, _published_labels(session, document)),
    )


def _splits(text: str) -> tuple[tuple[int, str | None], ...]:
    found: list[tuple[int, str | None]] = []
    for at in boundaries(text):
        opening = opening_number(text[at:])
        found.append((at, opening[0] if opening else None))
    return tuple(found)


def _suggestions(roots: list[Part], flags: Sequence[ParseFlag]) -> dict[int, FlagSuggestion]:
    """The suggested fixes of the open flags, each while it can still be made."""
    wanted = [
        flag
        for flag in flags
        if flag.suggestion and flag.accepted_at is None and flag.resolved_at is None
    ]
    if not wanted:
        return {}
    rows = {part.row: part for part in walk_parts(roots)}
    found: dict[int, FlagSuggestion] = {}
    for flag in wanted:
        stored: dict[str, Any] = dict(flag.suggestion or {})
        named = stored.get("node")
        part = rows.get(uuid.UUID(named) if named else flag.node_id)
        edit = cast(Edit, stored.get("edit"))
        at = stored.get("at")
        if part is None or (at is not None and not isinstance(at, int)):
            continue
        if edit == "split":
            opening = opening_number(part.text[at:]) if at is not None else None
            if opening is None or opening[0] != stored.get("label"):
                continue
        if possible(roots, edit, part.key, at):
            found[flag.position] = FlagSuggestion(edit=edit, key=part.key, at=at)
    return found


def accept_flags(
    session: Session,
    slug: str,
    positions: Sequence[int] | None,
    *,
    actor: Actor,
    expected_revision: int | None = None,
) -> DraftView:
    """Accept flags by their place in the draft's list, or every open one."""
    document = _document(session, slug)
    draft = _require_draft(session, document, lock=True, expected_revision=expected_revision)
    flags = {
        flag.position: flag
        for flag in session.scalars(
            select(ParseFlag).where(ParseFlag.document_version_id == draft.id)
        )
    }
    wanted = sorted(flags) if positions is None else sorted(set(positions))
    missing = [position for position in wanted if position not in flags]
    if missing:
        raise FlagNotFound(
            f"{slug}'s draft has no flag {', '.join(str(position) for position in missing)}."
        )
    now = datetime.now(UTC)
    accepted = []
    for position in wanted:
        flag = flags[position]
        if flag.accepted_at is not None or flag.resolved_at is not None:
            continue
        flag.accepted_at = now
        flag.accepted_by_user_id = actor.user_id
        accepted.append(flag)
    if accepted:
        _changed(draft, actor)
        record(
            session,
            actor=actor,
            action=DOCUMENT_FLAG_ACCEPTED,
            target_type="document_version",
            target_id=str(draft.id),
            details={
                "document": slug,
                "title": document.title,
                "version": draft.version_number,
                "flags": [
                    {"position": f.position, "kind": f.kind, "key": f.canonical_key}
                    for f in accepted
                ],
            },
        )
    session.flush()
    return read_draft(session, slug, version=draft)


def edit_draft(
    session: Session,
    slug: str,
    *,
    actor: Actor,
    title: str | None = None,
    effective_date: date | None = None,
    version_label: str | None = None,
    expected_revision: int | None = None,
) -> DraftView:
    """Change a draft's details before it is published."""
    document = _document(session, slug)
    draft = _require_draft(session, document, lock=True, expected_revision=expected_revision)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if title is not None and title.strip() and title.strip() != document.title:
        before["title"], after["title"] = document.title, title.strip()
        document.title = title.strip()
    if effective_date is not None and effective_date != draft.effective_date:
        before["effective_date"] = draft.effective_date.isoformat()
        after["effective_date"] = effective_date.isoformat()
        draft.effective_date = effective_date
    if version_label is not None and version_label.strip() != (draft.version_label or ""):
        before["version_label"], after["version_label"] = draft.version_label, version_label.strip()
        draft.version_label = version_label.strip() or None
    if after:
        _changed(draft, actor)
        record(
            session,
            actor=actor,
            action=DOCUMENT_DRAFT_EDITED,
            target_type="document_version",
            target_id=str(draft.id),
            details={"document": slug, "title": document.title, "before": before, "after": after},
        )
    session.flush()
    return read_draft(session, slug, version=draft)


def publish(
    session: Session, slug: str, *, actor: Actor, expected_revision: int | None = None
) -> VersionView:
    """Publish the draft: immutable from now on, searched once in force, and queued to embed."""
    document = _document(session, slug)
    draft = _require_draft(session, document, lock=True, expected_revision=expected_revision)
    open_flags = session.scalars(
        select(ParseFlag.position)
        .where(
            ParseFlag.document_version_id == draft.id,
            ParseFlag.accepted_at.is_(None),
            ParseFlag.resolved_at.is_(None),
        )
        .order_by(ParseFlag.position)
    ).all()
    if open_flags:
        raise FlagsOpen(slug, list(open_flags))
    latest = _latest_published(session, document)
    if latest is not None and draft.effective_date <= latest.effective_date:
        raise EffectiveDateTooEarly(
            f"Version {latest.version_label} of {slug} takes effect on "
            f"{latest.effective_date.isoformat()}. A new version has to take effect after it."
        )
    labels = _published_labels(session, document)
    if draft.version_label in labels:
        raise LabelTaken(
            f"{slug} has a version {draft.version_label} already. Give this one another label."
        )
    label = _label_for(draft, labels)
    restored = document.status == "archived"
    job = queue_indexing(session, draft.id)
    draft.version_label = label
    draft.status = "published"
    draft.published_at = datetime.now(UTC)
    draft.published_by_user_id = actor.user_id
    draft.index_job_id = job
    # A new version of an archived policy is the way back: publishing it is the decision.
    document.status = "active"
    session.flush()
    record(
        session,
        actor=actor,
        action=DOCUMENT_PUBLISHED,
        target_type="document_version",
        target_id=str(draft.id),
        details={
            "document": slug,
            "title": document.title,
            "version": label,
            "effective_date": draft.effective_date.isoformat(),
            "restored": restored,
        },
    )
    return _version_view(session, document, draft)


def reject_match(
    session: Session,
    slug: str,
    key: str,
    *,
    actor: Actor,
    expected_revision: int | None = None,
) -> DraftView:
    """Say a clause of the draft is a different rule from the one it was matched to.

    The clause becomes new and the earlier one removed, so that a citation of the earlier one says
    its rule was removed instead of pointing at this one. The flag that asked about the match is
    resolved by the change, and the other matching flags are written again, so that what they say
    about where each earlier rule went stays true.
    """
    document = _document(session, slug)
    draft = _require_draft(session, document, lock=True, expected_revision=expected_revision)
    node = session.scalars(
        select(DocumentNode).where(
            DocumentNode.document_version_id == draft.id, DocumentNode.canonical_key == key
        )
    ).first()
    if node is None:
        raise NoMatch(f"{slug}'s draft has no clause {key}.")
    if node.previous_node_id is None:
        raise NoMatch(f"{key} is new in {slug}'s draft: it continues no earlier clause.")
    earlier, words_then = session.execute(
        select(DocumentNode, NodeText)
        .join(NodeText, NodeText.node_id == DocumentNode.id)
        .where(DocumentNode.id == node.previous_node_id, NodeText.is_authoritative)
    ).one()
    node.previous_node_id = None
    node.change_type = "added"
    checks: dict[str, Any] = dict(draft.parse_checks or {})
    gone = {
        "key": earlier.canonical_key,
        "heading": words_then.heading,
        "text": words_then.body_text,
    }
    checks["removed"] = sorted(
        [*checks.get("removed", []), gone], key=lambda clause: clause["key"] or ""
    )
    # Kept, so that matching the clause again after a fix never pairs it with that rule again.
    checks["rejected"] = [
        *checks.get("rejected", []),
        {"node": str(node.id), "earlier": str(earlier.id)},
    ]
    draft.parse_checks = checks
    session.flush()

    flags = session.scalars(
        select(ParseFlag).where(
            ParseFlag.document_version_id == draft.id, ParseFlag.kind == "unmatched_key"
        )
    ).all()
    now = datetime.now(UTC)
    for flag in flags:
        if flag.canonical_key == key:
            # The latest decision stands: a match accepted earlier and rejected now is rejected.
            flag.accepted_at = None
            flag.accepted_by_user_id = None
            flag.resolved_at = now
            flag.resolved_by_user_id = actor.user_id
            flag.resolution = MATCH_REJECTED
    _rewrite_matching_flags(session, document, draft, flags, keep=key)
    _changed(draft, actor)
    session.flush()
    record(
        session,
        actor=actor,
        action=DOCUMENT_MATCH_REJECTED,
        target_type="document_version",
        target_id=str(draft.id),
        details={
            "document": slug,
            "title": document.title,
            "version": draft.version_number,
            "key": key,
            "earlier": earlier.canonical_key,
            "previous": checks.get("previous"),
        },
    )
    return read_draft(session, slug, version=draft)


def _rewrite_matching_flags(
    session: Session,
    document: Document,
    draft: DocumentVersion,
    flags: Sequence[ParseFlag],
    *,
    keep: str,
) -> None:
    """Write the matching flags' sentences again from the matches as they now stand. The flag
    on `keep` says what was decided about, so it keeps its words."""
    previous = _latest_published(session, document)
    label = (draft.parse_checks or {}).get("previous")
    if previous is None or not isinstance(label, str):
        return
    earlier = _earlier(session, previous)
    by_id = {clause.id: clause for clause in earlier}
    later: dict[str, Later] = {}
    matches: dict[str, Match] = {}
    for node, text in session.execute(
        select(DocumentNode, NodeText)
        .join(NodeText, NodeText.node_id == DocumentNode.id)
        .where(DocumentNode.document_version_id == draft.id, NodeText.is_authoritative)
    ).all():
        new = Later(node.canonical_key, node.label, text.heading, text.body_text)
        later[new.key] = new
        old = by_id.get(node.previous_node_id) if node.previous_node_id else None
        matches[new.key] = Match(
            change=cast(Change, node.change_type or "added"),
            earlier=old,
            score=similarity(words(new), words(old)) if old else 1.0,
        )
    matching = Matching(matches=matches, reused=reused(earlier, matches))
    said = {
        flag.key: flag.detail
        for flag in _matching_flags(matching, later, document.slug, label)
        if flag.key is not None
    }
    for flag in flags:
        key = flag.canonical_key
        if key is not None and key != keep and key in said:
            flag.detail = said[key]


def _positions(node: DocumentNode) -> list[int]:
    anchor: dict[str, Any] = dict(node.source_anchor or {})
    return [int(at) for at in anchor.get("positions", [])]


def _parts(session: Session, version: DocumentVersion) -> list[Part]:
    """A version's clauses as the fixing tools reshape them."""
    rows = session.execute(
        select(DocumentNode, NodeText)
        .join(NodeText, NodeText.node_id == DocumentNode.id)
        .where(DocumentNode.document_version_id == version.id, NodeText.is_authoritative)
    ).all()
    return _parts_of([(node, text) for node, text in rows])


def _parts_of(rows: Sequence[tuple[DocumentNode, NodeText]]) -> list[Part]:
    children: dict[uuid.UUID | None, list[tuple[DocumentNode, NodeText]]] = {}
    for node, text in rows:
        children.setdefault(node.parent_node_id, []).append((node, text))

    def build(parent: uuid.UUID | None) -> list[Part]:
        found = sorted(children.get(parent, []), key=lambda pair: pair[0].order_index)
        return [
            Part(
                kind=node.node_type,
                layer=cast(Layer, node.parse_layer or "native_structure"),
                label=node.label,
                heading=text.heading,
                lines=text.body_text.split("\n") if text.body_text else [],
                positions=_positions(node),
                children=build(node.id),
                row=node.id,
                previous=node.previous_node_id,
                fixed=node.fixed,
                change=node.change_type,
                key=node.canonical_key,
                lang=text.lang,
            )
            for node, text in found
        ]

    return build(None)


def _change_of(new: Later, old: Earlier | None) -> Change:
    """What a clause did to the earlier one it continues, as matching an upload says it."""
    if old is None:
        return "added"
    if old.key != new.key:
        return "moved"
    return "unchanged" if words(new) == words(old) else "modified"


def _match_again(
    session: Session,
    document: Document,
    roots: list[Part],
    result: Result,
    checks: dict[str, Any],
) -> tuple[Matching, dict[str, Later], str] | None:
    """For a new version: the clauses a change reworded are matched again, by the rules an upload
    uses, against the earlier clauses nothing continues, never to a rule a reviewer said is a
    different one. Then every clause's change is worked out again from its key and its words."""
    previous = _latest_published(session, document)
    label = checks.get("previous")
    if previous is None or not isinstance(label, str):
        return None
    earlier = _earlier(session, previous)
    by_id = {clause.id: clause for clause in earlier}
    parts = list(walk_parts(roots))
    for part in result.reworded:
        part.previous = None
    taken = {part.previous for part in parts if part.previous}
    free = [clause for clause in earlier if clause.id not in taken]
    rejected = {(item["node"], item["earlier"]) for item in checks.get("rejected", [])}
    if result.reworded and free:
        reworded = {part.key: part for part in result.reworded}
        again = match(free, [Later(p.key, p.label, p.heading, p.text) for p in result.reworded])
        for key, found in again.matches.items():
            part = reworded[key]
            if found.earlier is not None and (str(part.row), str(found.earlier.id)) not in rejected:
                part.previous = found.earlier.id
    later: dict[str, Later] = {}
    matches: dict[str, Match] = {}
    for part in parts:
        new = Later(part.key, part.label, part.heading, part.text)
        old = by_id.get(part.previous) if part.previous else None
        change = _change_of(new, old)
        part.previous = old.id if old else None
        part.change = change
        later[part.key] = new
        matches[part.key] = Match(
            change=change, earlier=old, score=similarity(words(new), words(old)) if old else 1.0
        )
    continued = {part.previous for part in parts if part.previous}
    removed = [clause for clause in earlier if clause.id not in continued]
    checks["removed"] = [
        {"key": gone.key, "heading": gone.heading, "text": gone.text}
        for gone in sorted(removed, key=lambda clause: clause.key)
    ]
    matching = Matching(matches=matches, removed=removed, reused=reused(earlier, matches))
    return matching, later, label


def _store_parts(session: Session, draft: DocumentVersion, roots: list[Part]) -> None:
    """Write the reshaped tree back. A key that changes goes through a name no key can have,
    so two clauses trading keys never break the rule that a key names one clause."""
    nodes = {
        node.id: node
        for node in session.scalars(
            select(DocumentNode).where(DocumentNode.document_version_id == draft.id)
        )
    }
    texts = {
        text.node_id: text
        for text in session.scalars(
            select(NodeText).where(NodeText.node_id.in_(list(nodes)), NodeText.is_authoritative)
        )
    }
    kept = {part.row: part for part in walk_parts(roots) if part.row is not None}
    for row, node in nodes.items():
        if row not in kept or kept[row].key != node.canonical_key:
            node.canonical_key = f"~{row}"
    session.flush()

    def put(part: Part, parent: DocumentNode | None, order: int, depth: int) -> None:
        node = nodes.get(part.row) if part.row else None
        if node is None:
            node = DocumentNode(document_version_id=draft.id, is_normative=True)
            session.add(node)
        node.canonical_key = part.key
        node.parent_node_id = parent.id if parent else None
        node.node_type = part.kind
        node.label = part.label
        node.order_index = order
        node.depth = depth
        node.parse_layer = part.layer
        node.source_anchor = {"positions": list(part.positions)}
        node.previous_node_id = part.previous
        node.change_type = part.change
        node.fixed = part.fixed
        session.flush()
        part.row = node.id
        text = texts.get(node.id)
        if text is None:
            text = NodeText(node_id=node.id, is_authoritative=True, translation_status="original")
            session.add(text)
        text.lang = part.lang
        text.heading = part.heading
        text.label = part.label
        text.body_text = part.text
        for index, child in enumerate(part.children):
            put(child, node, index, depth + 1)

    for index, root in enumerate(roots):
        put(root, None, index, 0)
    session.flush()


KEYS_COLLIDED = re.compile(r".+ names \d+ clauses\.")
"""How the check that every key names one clause says two do."""


def _in_sequence(roots: list[Part], row: uuid.UUID | None) -> bool:
    """Whether a clause still follows a sibling numbered in its own style. A numbering flag the
    checks no longer raise is settled only then: its numbers now run in order, rather than the
    clause having been moved away from the numbers it was out of step with."""

    def look(siblings: list[Part]) -> bool | None:
        for index, part in enumerate(siblings):
            if part.row == row:
                label = parse_label(part.label) if part.label else None
                if label is None or label.bullet:
                    return False
                styles = {style for style, _ in label.readings()}
                for before in siblings[:index]:
                    other = parse_label(before.label) if before.label else None
                    if other is not None and styles & {style for style, _ in other.readings()}:
                        return True
                return False
            found = look(part.children)
            if found is not None:
                return found
        return None

    return row is not None and bool(look(roots))


def _settle_flags(
    session: Session,
    document: Document,
    draft: DocumentVersion,
    roots: list[Part],
    clauses: tuple[Clause, ...],
    result: Result,
    edit: Edit,
    matched: tuple[Matching, dict[str, Later], str] | None,
    actor: Actor,
) -> tuple[list[int], list[int]]:
    """Flags after a fix: each follows its clause to its new key; an open one on the fixed
    clause, or one the change made untrue, is resolved by it; and what the checks and the
    matching find now that no flag says is a new flag. Returns the flags settled and added."""
    flags = list(
        session.scalars(
            select(ParseFlag)
            .where(ParseFlag.document_version_id == draft.id)
            .order_by(ParseFlag.position)
        )
    )
    rows = {part.row: part for part in walk_parts(roots) if part.row is not None}
    gone = {part.row for part in result.gone}
    now = datetime.now(UTC)
    settled: list[int] = []

    def resolve(flag: ParseFlag) -> None:
        flag.resolved_at = now
        flag.resolved_by_user_id = actor.user_id
        flag.resolution = DONE[edit]
        flag.resolution_key = result.named.key if result.named else None
        settled.append(flag.position)

    def open_(flag: ParseFlag) -> bool:
        return flag.accepted_at is None and flag.resolved_at is None

    numbering = [*check_numbering(clauses), *check_keys(clauses)]
    found_numbering = {(flag.detail, flag.key) for flag in numbering}
    standing: dict[str, Flag] = {}
    fresh: list[Flag] = []
    if matched is not None:
        matching, later, label = matched
        standing = {
            flag.key: flag
            for flag in _matching_flags(matching, later, document.slug, label)
            if flag.key
        }
        quiet = frozenset(part.key for part in result.marked if part not in result.reworded)
        fresh = _matching_flags(matching, later, document.slug, label, quiet)

    for flag in flags:
        if flag.node_id in gone:
            if open_(flag):
                resolve(flag)
            flag.node_id = None
            continue
        if flag.node_id in rows:
            flag.canonical_key = rows[flag.node_id].key
        if flag.kind == "unmatched_key" and flag.accepted_at is not None:
            said = standing.get(flag.canonical_key or "")
            if said is not None:
                flag.detail = said.detail
        if not open_(flag):
            continue
        if flag.node_id is not None and flag.node_id == result.subject.row:
            resolve(flag)
        elif flag.kind == "numbering_gap":
            untrue = (flag.detail, flag.canonical_key) not in found_numbering
            collided = KEYS_COLLIDED.fullmatch(flag.detail) is not None
            if untrue and (collided or _in_sequence(roots, flag.node_id)):
                resolve(flag)
        elif flag.kind == "unmatched_key" and matched is not None:
            said = standing.get(flag.canonical_key or "")
            if said is None:
                resolve(flag)
            else:
                flag.detail = said.detail

    held = {
        (flag.kind, flag.detail, flag.canonical_key)
        for flag in flags
        if flag.resolved_at is None and flag.kind == "numbering_gap"
    }
    matched_keys = {
        flag.canonical_key
        for flag in flags
        if flag.resolved_at is None and flag.kind == "unmatched_key"
    }
    order = {part.key: index for index, part in enumerate(walk_parts(roots))}
    new = [
        *(flag for flag in numbering if (flag.kind, flag.detail, flag.key) not in held),
        *(flag for flag in fresh if flag.key not in matched_keys),
    ]
    by_key = {part.key: part.row for part in walk_parts(roots) if part.row is not None}
    position = max((flag.position for flag in flags), default=0)
    added: list[int] = []
    for finding in sorted(new, key=lambda found: order.get(found.key or "", len(order))):
        position += 1
        session.add(
            ParseFlag(
                document_version_id=draft.id,
                node_id=by_key.get(finding.key) if finding.key else None,
                canonical_key=finding.key,
                kind=finding.kind,
                detail=finding.detail,
                position=position,
                suggestion=_stored(finding, by_key),
            )
        )
        added.append(position)
    session.flush()
    return settled, added


def fix_clause(
    session: Session,
    slug: str,
    edit: Edit,
    key: str,
    *,
    actor: Actor,
    at: int | None = None,
    expected_revision: int | None = None,
) -> FixedDraft:
    """Fix how a clause of the draft was read, without changing a word.

    Keys are given again by the rules a parse uses. An open flag on the clause is resolved by
    the change. The numbering checks run again, so a numbering flag the change makes untrue is
    resolved and a new finding is a new flag. For a new version, the clauses the change rewords
    are matched again, and every clause's change against the version before is worked out again.
    """
    document = _document(session, slug)
    draft = _require_draft(session, document, lock=True, expected_revision=expected_revision)
    roots = _parts(session, draft)
    part = locate(roots, key)
    if part is None:
        raise NoClause(f"{slug}'s draft has no clause {key}.")
    texts = {int(row["position"]): str(row["text"]) for row in draft.reading or []}
    result = apply(roots, edit, part, at, texts)
    clauses = keyed(document.slug, roots)
    for found in walk_parts(roots):
        if len(found.key) > MAX_KEY:
            raise CannotFix(
                f"A clause's key would be longer than {MAX_KEY} characters "
                f"({found.key[:60]}…), which nests it too deeply."
            )
    checks: dict[str, Any] = dict(draft.parse_checks or {})
    matched = _match_again(session, document, roots, result, checks)
    _store_parts(session, draft, roots)
    settled, added = _settle_flags(
        session, document, draft, roots, clauses, result, edit, matched, actor
    )
    for gone in result.gone:
        if gone.row is not None:
            session.execute(delete(NodeText).where(NodeText.node_id == gone.row))
            session.execute(delete(DocumentNode).where(DocumentNode.id == gone.row))
    draft.parse_checks = checks
    _changed(draft, actor)
    session.flush()
    record(
        session,
        actor=actor,
        action=DOCUMENT_CLAUSE_FIXED,
        target_type="document_version",
        target_id=str(draft.id),
        details={
            "document": slug,
            "title": document.title,
            "version": draft.version_number,
            "edit": edit,
            "key": key,
            "now": result.after.key,
            "with": result.named.key if result.named else None,
            "settled": settled,
            "flags": added,
        },
    )
    return FixedDraft(draft=read_draft(session, slug, version=draft), clause=result.after.key)


def _discard(
    session: Session, document: Document, draft: DocumentVersion, actor: Actor, reason: str
) -> None:
    draft.status = "discarded"
    record(
        session,
        actor=actor,
        action=DOCUMENT_DRAFT_DISCARDED,
        target_type="document_version",
        target_id=str(draft.id),
        details={
            "document": document.slug,
            "title": document.title,
            "version": draft.version_number,
            "reason": reason,
        },
    )


def discard(
    session: Session, slug: str, *, actor: Actor, expected_revision: int | None = None
) -> None:
    """Throw the draft away. It is kept as discarded, and nothing searches it."""
    document = _document(session, slug)
    draft = _require_draft(session, document, lock=True, expected_revision=expected_revision)
    _discard(session, document, draft, actor, reason="discarded")
    session.flush()


def archive(session: Session, slug: str, *, actor: Actor) -> None:
    """Hide a policy from search and the library. Nothing is deleted, citations still read, and
    publishing a new version of it brings it back."""
    document = _document(session, slug)
    draft = _draft_of(session, document, lock=True)
    if draft is not None:
        _discard(session, document, draft, actor, reason="the policy was archived")
    document.status = "archived"
    session.flush()
    record(
        session,
        actor=actor,
        action=DOCUMENT_ARCHIVED,
        target_type="document",
        target_id=str(document.id),
        details={"document": slug, "title": document.title},
    )


def _last_changes(session: Session) -> dict[str, LastChange]:
    """Who last did something to each policy, and when, as the governance log has it."""
    document = GovernanceEntry.details["document"].as_string()
    rows = session.execute(
        select(document, GovernanceEntry.occurred_at, GovernanceEntry.actor_user_id)
        .where(GovernanceEntry.action.in_(DOCUMENT_ACTIONS))
        .distinct(document)
        .order_by(document, GovernanceEntry.seq.desc())
    ).all()
    names = _names(session, [user for _, _, user in rows])
    return {
        slug: LastChange(by=names.get(user) if user else None, at=at)
        for slug, at, user in rows
        if slug
    }


def list_policies(session: Session) -> list[PolicySummary]:
    today = date.today()
    changes = _last_changes(session)
    summaries = []
    for document in session.scalars(
        select(Document).where(Document.kind == "org_policy").order_by(Document.slug)
    ):
        versions = session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number)
        ).all()
        published = [v for v in versions if v.status == "published"]
        in_force = [v for v in published if v.effective_date <= today]
        current = max(in_force, key=lambda v: v.effective_date, default=None)
        later = min(
            (v for v in published if v.effective_date > today),
            key=lambda v: v.effective_date,
            default=None,
        )
        draft = next((v for v in versions if v.status == "draft"), None)
        latest = published[-1] if published else None
        indexing = None
        if latest is not None and latest.index_job_id is not None:
            indexing = job_status(session, latest.index_job_id) or "succeeded"
        review = None
        if draft is not None:
            settled = session.execute(
                select(ParseFlag.accepted_at, ParseFlag.resolved_at).where(
                    ParseFlag.document_version_id == draft.id
                )
            ).all()
            uploader = draft.created_by_user_id
            review = DraftReview(
                flags=len(settled),
                open=sum(
                    1 for accepted, resolved in settled if accepted is None and resolved is None
                ),
                uploaded_by=_names(session, [uploader]).get(uploader) if uploader else None,
                uploaded_at=draft.created_at,
                next_label=_label_for(draft, {v.version_label for v in published}),
            )
        summaries.append(
            PolicySummary(
                slug=document.slug,
                title=document.title,
                status=document.status,
                in_force=current.version_label if current else None,
                in_force_since=current.effective_date if current else None,
                published=len(published),
                draft=draft.version_number if draft else None,
                indexing=indexing,
                in_force_number=current.version_number if current else None,
                next_label=_next_label({v.version_label for v in published}),
                sample=document.slug == SAMPLE_SLUG,
                scheduled=(
                    Scheduled(
                        label=later.version_label or str(later.version_number),
                        effective_date=later.effective_date,
                    )
                    if later
                    else None
                ),
                review=review,
                last_change=changes.get(document.slug),
            )
        )
    return summaries


def _numbered(session: Session, document: Document, number: int) -> DocumentVersion:
    found = session.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.version_number == number
        )
    ).first()
    if found is None:
        raise PolicyNotFound(f"{document.slug} has no version {number}.")
    return found


def version_status(session: Session, slug: str, number: int) -> str:
    """Whether a version is a draft, published or discarded, which decides who may see its file."""
    return _numbered(session, _document(session, slug), number).status


def file_as_read(session: Session, originals: Originals, slug: str, number: int) -> FileView:
    """A version's file as it was read: every paragraph in order, each with the clause it went
    to or the reason it was set aside."""
    document = _document(session, slug)
    version = _numbered(session, document, number)
    if version.reading is not None:
        lines = from_rows(version.reading)
    else:
        # Read before the file as read was kept with its version.
        data, name, _ = original(session, originals, slug, number)
        lines = lines_of(read_file(data, name))
    clauses: dict[int, list[str]] = {}
    for key, anchor in session.execute(
        select(DocumentNode.canonical_key, DocumentNode.source_anchor)
        .where(DocumentNode.document_version_id == version.id)
        .order_by(DocumentNode.depth, DocumentNode.order_index)
    ).all():
        where: dict[str, Any] = dict(anchor or {})
        for position in where.get("positions", []):
            clauses.setdefault(position, []).append(key)
    checks: dict[str, Any] = dict(version.parse_checks or {})
    set_aside = {
        position: block["reason"]
        for block in checks.get("set_aside", [])
        for position in block.get("positions", [])
    }
    return FileView(
        slug=slug,
        number=number,
        status=version.status,
        name=version.source_name,
        format=version.source_format,
        size=version.source_size,
        lines=tuple(
            FileLine(
                line=line,
                clause=next(iter(clauses.get(line.position, [])), None),
                set_aside=set_aside.get(line.position),
                clauses=tuple(clauses.get(line.position, [])),
            )
            for line in lines
            if line.text.strip()
        ),
    )


def original(
    session: Session, originals: Originals, slug: str, number: int
) -> tuple[bytes, str, str]:
    """A version's original file, checked against its size and hash, with its name and format."""
    document = _document(session, slug)
    version = session.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.version_number == number
        )
    ).first()
    if version is None or version.source_key is None or version.source_sha256 is None:
        raise PolicyNotFound(f"{slug} has no version {number} with an original file.")
    data = originals.get(
        Stored(key=version.source_key, size=version.source_size or 0, sha256=version.source_sha256)
    )
    return (
        data,
        version.source_name or f"{slug}.{version.source_format}",
        version.source_format or "",
    )


def load_sample(session: Session, originals: Originals, *, actor: Actor) -> bool:
    """Publish the made-up sample policy, once. Archived or not, it is never brought back."""
    if session.scalars(select(Document.id).where(Document.slug == SAMPLE_SLUG)).first():
        return False
    upload_policy(
        session,
        originals,
        SAMPLE.read_bytes(),
        SAMPLE.name,
        actor=actor,
        slug=SAMPLE_SLUG,
        effective_date=SAMPLE_EFFECTIVE,
        version_label="1",
    )
    accept_flags(session, SAMPLE_SLUG, None, actor=actor)
    publish(session, SAMPLE_SLUG, actor=actor)
    return True
