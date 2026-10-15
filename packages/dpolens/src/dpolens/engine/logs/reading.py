"""Reading the query log back: a page of questions, a clause's count, and the Overview's week.

Who may see what is decided by the caller, which has already checked the
permissions. Someone who may read only their own questions passes their id as
`only_user`. The asker is returned only when the caller asks for identities, and
the caller records that look in the governance log with `record_identities_viewed`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Text, and_, cast, exists, func, or_, select, tuple_
from sqlalchemy.orm import Session

from dpolens.engine.auth.models import User
from dpolens.engine.documents.models import Document, DocumentNode, DocumentVersion, NodeText
from dpolens.engine.logs.governance import QUERY_LOG_IDENTITIES_VIEWED, Actor, record
from dpolens.engine.logs.models import QueryLogEntry, QueryLogResult
from dpolens.engine.packs.models import Pack

MOST_CITED = 5
LATEST_UNANSWERED = 4
EXPORT_BATCH = 500

CITING = ("search", "get_clause")
"""What counts as citing a clause: a search that returned it first, or a read of
that one clause by its key. Reading a whole article in the library does not."""


@dataclass(frozen=True)
class ClauseName:
    """Enough to name a clause the way a reader cites it, in the language it was returned in."""

    key: str
    document_title: str
    document_slug: str
    pack_slug: str | None
    version_label: str | None
    lang: str
    trail: tuple[tuple[str | None, str | None], ...]
    """The label and heading of each clause from the outermost one down to this one."""


@dataclass(frozen=True)
class LoggedResult:
    rank: int
    name: ClauseName


@dataclass(frozen=True)
class LoggedQuestion:
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    surface: str
    operation: str
    query: str
    target: str | None
    status: str
    scope: str | None
    redaction_count: int
    redaction_types: tuple[str, ...]
    results: tuple[LoggedResult, ...]
    asker: User | None
    """Set only when the caller asked for identities."""


@dataclass(frozen=True)
class QuestionFilter:
    since: datetime | None = None
    until: datetime | None = None
    surfaces: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    operations: tuple[str, ...] = ("search",)
    document: str | None = None
    """A document slug: entries that returned anything from it."""
    text: str | None = None
    """Words in the question, or in the key that was read."""
    only_user: uuid.UUID | None = None
    asked_by: str | None = None
    """Words in the asker's name or address. Only meaningful with identities."""

    def described(self) -> dict[str, Any]:
        """The filter as the governance log records it, beside a look at names."""
        return {
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "surfaces": list(self.surfaces),
            "statuses": list(self.statuses),
            "operations": list(self.operations),
            "document": self.document,
            "text": self.text,
            "asked_by": self.asked_by,
        }


@dataclass(frozen=True)
class QuestionPage:
    questions: tuple[LoggedQuestion, ...]
    total: int
    next_cursor: tuple[datetime, uuid.UUID] | None


def _like(words: str) -> str:
    escaped = words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _conditions(found: QuestionFilter, identities: bool) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if found.since is not None:
        conditions.append(QueryLogEntry.created_at >= found.since)
    if found.until is not None:
        conditions.append(QueryLogEntry.created_at < found.until)
    if found.surfaces:
        conditions.append(QueryLogEntry.surface.in_(found.surfaces))
    if found.statuses:
        conditions.append(QueryLogEntry.status.in_(found.statuses))
    if found.operations:
        conditions.append(QueryLogEntry.operation.in_(found.operations))
    if found.only_user is not None:
        conditions.append(QueryLogEntry.actor_user_id == found.only_user)
    if found.text:
        pattern = _like(found.text)
        conditions.append(
            or_(
                QueryLogEntry.query_redacted.ilike(pattern, escape="\\"),
                QueryLogEntry.target.ilike(pattern, escape="\\"),
            )
        )
    if found.document:
        conditions.append(
            exists(
                select(QueryLogResult.id)
                .join(DocumentVersion, DocumentVersion.id == QueryLogResult.document_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    QueryLogResult.query_log_entry_id == QueryLogEntry.id,
                    Document.slug == found.document,
                )
            )
        )
    if found.asked_by and identities:
        pattern = _like(found.asked_by)
        conditions.append(
            exists(
                select(User.id).where(
                    User.id == QueryLogEntry.actor_user_id,
                    or_(
                        User.display_name.ilike(pattern, escape="\\"),
                        User.email.ilike(pattern, escape="\\"),
                    ),
                )
            )
        )
    return conditions


def _ancestor_keys(key: str) -> list[str]:
    """A key and the keys above it. Keys carry their hierarchy: art-17, then art-17:para-1."""
    parts = key.split(":")
    return [":".join(parts[:end]) for end in range(2, len(parts) + 1)] or [key]


def name_clauses(
    session: Session, wanted: Iterable[tuple[uuid.UUID, str, str]]
) -> dict[tuple[uuid.UUID, str], ClauseName]:
    """Names for many clauses at once, each by version, key and language.

    Two queries however many there are: one for the versions and their documents,
    one for the labels and headings of every clause and of the clauses above them.
    """
    asked = set(wanted)
    if not asked:
        return {}

    versions = {
        version.id: (version, document, pack)
        for version, document, pack in session.execute(
            select(DocumentVersion, Document, Pack)
            .join(Document, Document.id == DocumentVersion.document_id)
            .outerjoin(Pack, Pack.id == Document.pack_id)
            .where(DocumentVersion.id.in_({version_id for version_id, _, _ in asked}))
        ).all()
    }
    pairs = {
        (version_id, ancestor) for version_id, key, _ in asked for ancestor in _ancestor_keys(key)
    }
    texts: dict[tuple[uuid.UUID, str], dict[str, tuple[str | None, str | None, bool]]] = {}
    for version_id, key, node_label, lang, label, heading, authoritative in session.execute(
        select(
            DocumentNode.document_version_id,
            DocumentNode.canonical_key,
            DocumentNode.label,
            NodeText.lang,
            NodeText.label,
            NodeText.heading,
            NodeText.is_authoritative,
        )
        .join(NodeText, NodeText.node_id == DocumentNode.id)
        .where(tuple_(DocumentNode.document_version_id, DocumentNode.canonical_key).in_(pairs))
    ).all():
        texts.setdefault((version_id, key), {})[lang] = (
            label or node_label,
            heading,
            authoritative,
        )

    def words(version_id: uuid.UUID, key: str, lang: str) -> tuple[str | None, str | None] | None:
        by_lang = texts.get((version_id, key))
        if not by_lang:
            return None
        chosen = by_lang.get(lang) or next(
            (text for text in by_lang.values() if text[2]), next(iter(by_lang.values()))
        )
        return chosen[0], chosen[1]

    names: dict[tuple[uuid.UUID, str], ClauseName] = {}
    for version_id, key, lang in asked:
        found = versions.get(version_id)
        if found is None:
            continue
        version, document, pack = found
        trail = tuple(
            named
            for ancestor in _ancestor_keys(key)
            if (named := words(version_id, ancestor, lang)) is not None
        )
        names[(version_id, key)] = ClauseName(
            key=key,
            document_title=document.title,
            document_slug=document.slug,
            pack_slug=pack.slug if pack else None,
            version_label=version.version_label,
            lang=lang,
            trail=trail,
        )
    return names


def _assemble(
    session: Session, entries: Sequence[QueryLogEntry], identities: bool
) -> list[LoggedQuestion]:
    if not entries:
        return []
    results = session.execute(
        select(
            QueryLogResult.query_log_entry_id,
            QueryLogResult.rank,
            QueryLogResult.document_version_id,
            QueryLogResult.canonical_key,
            QueryLogResult.lang,
        )
        .where(QueryLogResult.query_log_entry_id.in_([entry.id for entry in entries]))
        .order_by(QueryLogResult.query_log_entry_id, QueryLogResult.rank)
    ).all()
    names = name_clauses(
        session, ((row.document_version_id, row.canonical_key, row.lang) for row in results)
    )
    by_entry: dict[uuid.UUID, list[LoggedResult]] = {}
    for row in results:
        name = names.get((row.document_version_id, row.canonical_key))
        if name is not None:
            by_entry.setdefault(row.query_log_entry_id, []).append(LoggedResult(row.rank, name))

    askers: dict[uuid.UUID, User] = {}
    if identities:
        askers = {
            user.id: user
            for user in session.scalars(
                select(User).where(User.id.in_({entry.actor_user_id for entry in entries}))
            )
        }

    return [
        LoggedQuestion(
            id=entry.id,
            created_at=entry.created_at,
            expires_at=entry.expires_at,
            surface=entry.surface,
            operation=entry.operation,
            query=entry.query_redacted,
            target=entry.target,
            status=entry.status,
            scope=entry.scope,
            redaction_count=entry.redaction_count,
            redaction_types=tuple(entry.redaction_types),
            results=tuple(by_entry.get(entry.id, ())),
            asker=askers.get(entry.actor_user_id) if identities else None,
        )
        for entry in entries
    ]


def page_of_questions(
    session: Session,
    found: QuestionFilter,
    *,
    limit: int,
    before: tuple[datetime, uuid.UUID] | None = None,
    identities: bool = False,
) -> QuestionPage:
    """The newest questions first, a page at a time, with how many there are in all."""
    conditions = _conditions(found, identities)
    total = session.scalar(select(func.count()).select_from(QueryLogEntry).where(*conditions))
    query = select(QueryLogEntry).where(*conditions)
    if before is not None:
        query = query.where(tuple_(QueryLogEntry.created_at, QueryLogEntry.id) < before)
    entries = session.scalars(
        query.order_by(QueryLogEntry.created_at.desc(), QueryLogEntry.id.desc()).limit(limit + 1)
    ).all()
    more = len(entries) > limit
    shown = entries[:limit]
    return QuestionPage(
        questions=tuple(_assemble(session, shown, identities)),
        total=int(total or 0),
        next_cursor=(shown[-1].created_at, shown[-1].id) if more and shown else None,
    )


def all_questions(
    session: Session, found: QuestionFilter, *, identities: bool = False
) -> Iterator[LoggedQuestion]:
    """Every question the filter selects, newest first, read in batches for an export."""
    before: tuple[datetime, uuid.UUID] | None = None
    while True:
        page = page_of_questions(
            session, found, limit=EXPORT_BATCH, before=before, identities=identities
        )
        yield from page.questions
        if page.next_cursor is None:
            return
        before = page.next_cursor


def record_identities_viewed(
    session: Session,
    *,
    actor: Actor,
    found: QuestionFilter,
    entry_ids: Sequence[uuid.UUID] = (),
    exported: int | None = None,
) -> None:
    """A look at who asked, written before the names leave the instance.

    A page records the entries it showed. An export, which can be a year of
    questions, records how many it holds, as `exported`, and with what filter.
    """
    details: dict[str, Any] = {"filters": found.described()}
    if exported is not None:
        details["count"] = exported
        details["exported"] = True
    else:
        details["count"] = len(entry_ids)
        details["entries"] = [str(entry_id) for entry_id in entry_ids]
    record(
        session,
        actor=actor,
        action=QUERY_LOG_IDENTITIES_VIEWED,
        target_type="query_log",
        target_id=datetime.now(UTC).date().isoformat(),
        details=details,
    )


# The Overview and a clause's count ---------------------------------------------


@dataclass(frozen=True)
class Window:
    """Whole days in the reader's own time zone, the last of them today."""

    days: int
    zone: ZoneInfo
    since: datetime
    until: datetime

    @classmethod
    def ending_today(cls, days: int, zone: ZoneInfo, now: datetime | None = None) -> Window:
        now = now or datetime.now(UTC)
        today = now.astimezone(zone).date()
        start = datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=zone)
        return cls(days=days, zone=zone, since=start.astimezone(UTC), until=now)

    def dates(self) -> list[date]:
        first = self.since.astimezone(self.zone).date()
        return [first + timedelta(days=offset) for offset in range(self.days)]

    def before(self) -> tuple[datetime, datetime]:
        """The same number of days just before, for a comparison."""
        return self.since - timedelta(days=self.days), self.since


@dataclass(frozen=True)
class Day:
    day: date
    assistants: int
    dashboard: int
    other: int


@dataclass(frozen=True)
class Cited:
    name: ClauseName
    count: int


@dataclass(frozen=True)
class Source:
    """Where answers came from: a law, by its pack, or the organisation's policies."""

    pack_slug: str | None
    title: str
    count: int


@dataclass(frozen=True)
class Week:
    window: Window
    questions: int
    previous: int
    answered: int
    found_nothing: int
    by_day: tuple[Day, ...]
    most_cited: tuple[Cited, ...]
    sources: tuple[Source, ...]
    unanswered: tuple[LoggedQuestion, ...]


def _local_day(window: Window) -> ColumnElement[date]:
    return func.date(func.timezone(window.zone.key, QueryLogEntry.created_at))


def overview(session: Session, window: Window) -> Week:
    """What the Overview shows, for anyone who may read every question. Names never."""
    searches = and_(
        QueryLogEntry.operation == "search",
        QueryLogEntry.created_at >= window.since,
        QueryLogEntry.created_at < window.until,
    )
    counts: dict[str, int] = {
        status: int(count)
        for status, count in session.execute(
            select(QueryLogEntry.status, func.count())
            .where(searches)
            .group_by(QueryLogEntry.status)
        ).all()
    }
    earlier, later = window.before()
    previous = session.scalar(
        select(func.count())
        .select_from(QueryLogEntry)
        .where(
            QueryLogEntry.operation == "search",
            QueryLogEntry.created_at >= earlier,
            QueryLogEntry.created_at < later,
        )
    )

    per_day: dict[date, dict[str, int]] = {}
    day = _local_day(window)
    for local, surface, count in session.execute(
        select(day, QueryLogEntry.surface, func.count())
        .where(searches)
        .group_by(day, QueryLogEntry.surface)
    ).all():
        per_day.setdefault(local, {})[surface] = int(count)
    by_day = tuple(
        Day(
            day=local,
            assistants=per_day.get(local, {}).get("mcp", 0),
            dashboard=per_day.get(local, {}).get("dashboard", 0),
            other=sum(
                count
                for surface, count in per_day.get(local, {}).items()
                if surface not in ("mcp", "dashboard")
            ),
        )
        for local in window.dates()
    )

    first = (
        select(
            QueryLogResult.canonical_key,
            # Postgres has no max() for a uuid; any version of the clause will do to name it.
            func.max(cast(QueryLogResult.document_version_id, Text)).label("version"),
            func.max(QueryLogResult.lang).label("lang"),
            func.count().label("cited"),
        )
        .join(QueryLogEntry, QueryLogEntry.id == QueryLogResult.query_log_entry_id)
        .where(
            QueryLogResult.rank == 1,
            QueryLogEntry.status == "ok",
            QueryLogEntry.operation.in_(CITING),
            QueryLogEntry.created_at >= window.since,
            QueryLogEntry.created_at < window.until,
        )
        .group_by(QueryLogResult.canonical_key)
        .order_by(func.count().desc(), QueryLogResult.canonical_key)
        .limit(MOST_CITED)
    )
    top = session.execute(first).all()
    names = name_clauses(
        session, ((uuid.UUID(row.version), row.canonical_key, row.lang) for row in top)
    )
    most_cited = tuple(
        Cited(name=names[(uuid.UUID(row.version), row.canonical_key)], count=int(row.cited))
        for row in top
        if (uuid.UUID(row.version), row.canonical_key) in names
    )

    sources = tuple(
        Source(pack_slug=slug, title=title, count=int(count))
        for slug, title, count in session.execute(
            select(Pack.slug, func.min(Document.title), func.count())
            .select_from(QueryLogResult)
            .join(QueryLogEntry, QueryLogEntry.id == QueryLogResult.query_log_entry_id)
            .join(DocumentVersion, DocumentVersion.id == QueryLogResult.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .outerjoin(Pack, Pack.id == Document.pack_id)
            .where(searches, QueryLogEntry.status == "ok", QueryLogResult.rank == 1)
            .group_by(Pack.slug)
            .order_by(func.count().desc())
        ).all()
    )

    latest = session.scalars(
        select(QueryLogEntry)
        .where(searches, QueryLogEntry.status == "no_match")
        .order_by(QueryLogEntry.created_at.desc(), QueryLogEntry.id.desc())
        .limit(LATEST_UNANSWERED)
    ).all()

    return Week(
        window=window,
        questions=sum(int(count) for count in counts.values()),
        previous=int(previous or 0),
        answered=int(counts.get("ok", 0)),
        found_nothing=int(counts.get("no_match", 0)),
        by_day=by_day,
        most_cited=most_cited,
        sources=sources,
        unanswered=tuple(_assemble(session, latest, identities=False)),
    )


@dataclass(frozen=True)
class Activity:
    window: Window
    total: int
    by_day: tuple[tuple[date, int], ...]


def clause_activity(session: Session, key: str, window: Window) -> Activity:
    """How often one clause was cited in the window, counted as the Overview counts."""
    day = _local_day(window)
    counts: Mapping[date, int] = {
        local: int(count)
        for local, count in session.execute(
            select(day, func.count())
            .select_from(QueryLogResult)
            .join(QueryLogEntry, QueryLogEntry.id == QueryLogResult.query_log_entry_id)
            .where(
                QueryLogResult.canonical_key == key,
                QueryLogResult.rank == 1,
                QueryLogEntry.status == "ok",
                QueryLogEntry.operation.in_(CITING),
                QueryLogEntry.created_at >= window.since,
                QueryLogEntry.created_at < window.until,
            )
            .group_by(day)
        ).all()
    }
    by_day = tuple((local, counts.get(local, 0)) for local in window.dates())
    return Activity(window=window, total=sum(count for _, count in by_day), by_day=by_day)
