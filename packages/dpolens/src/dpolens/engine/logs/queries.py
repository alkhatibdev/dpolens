"""Writing the query log, and deleting from it when the operator has set a retention.

Every call is recorded, including the ones that found nothing. A question the
corpus failed to answer is the most useful row in this table: it is a developer's
real phrasing, and the eval sets are supposed to grow from exactly that.

Questions are kept unless a retention is set: they are the organisation's record of
what its people needed to know. Where one is set, the instance deletes what is past it
itself rather than leaving it to somebody's cron, because a retention promise that
depends on the operator having read the documentation is a promise most instances
quietly break.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import Document, DocumentVersion
from dpolens.engine.documents.read import ClauseView
from dpolens.engine.logs.governance import Actor, record
from dpolens.engine.logs.models import QueryLogEntry, QueryLogResult
from dpolens.engine.logs.redaction import redact

QUERY_LOG_PURGED = "query_log.retention_purged"

PURGE_LOCK = int.from_bytes(
    hashlib.sha256(b"dpolens.query_log.purge").digest()[:8], "big", signed=True
)
"""One purge at a time, so several workers running the same daily job are
harmless rather than a race."""


@dataclass(frozen=True)
class Returned:
    """One result as the log keeps it: a pointer, not a copy of the text."""

    key: str
    lang: str
    document_slug: str
    version_label: str | None
    trust_tier: str | None

    @classmethod
    def of(cls, view: ClauseView) -> Returned:
        return cls(
            key=view.key,
            lang=view.lang,
            document_slug=view.document_slug,
            version_label=view.version_label,
            trust_tier=view.trust_tier,
        )


def record_query(
    session: Session,
    *,
    user_id: uuid.UUID,
    pat_id: uuid.UUID | None,
    surface: str,
    operation: str,
    status: str,
    query: str = "",
    target: str | None = None,
    results: Sequence[Returned] = (),
    redaction_patterns: Mapping[str, str] | None = None,
    scope: str | None = None,
) -> uuid.UUID:
    """Store what was asked, redacted, with what it returned.

    The raw question is redacted here and nowhere else, so there is no path by
    which it reaches storage unredacted. `scope` says whether a search stayed
    inside the selected laws.
    """
    hidden = redact(query, redaction_patterns) if query else redact("")

    entry = QueryLogEntry(
        actor_user_id=user_id,
        actor_pat_id=pat_id,
        surface=surface,
        operation=operation,
        query_redacted=hidden.text,
        target=target,
        redaction_count=hidden.count,
        redaction_types=list(hidden.types),
        status=status,
        scope=scope,
    )
    session.add(entry)
    session.flush()

    versions = _version_ids(session, results)
    for rank, returned in enumerate(results, start=1):
        version_id = versions.get((returned.document_slug, returned.version_label))
        if version_id is None:
            continue
        session.add(
            QueryLogResult(
                query_log_entry_id=entry.id,
                rank=rank,
                document_version_id=version_id,
                canonical_key=returned.key,
                lang=returned.lang,
                trust_tier=returned.trust_tier,
            )
        )
    session.flush()
    return entry.id


def _version_ids(
    session: Session, results: Sequence[Returned]
) -> dict[tuple[str, str | None], uuid.UUID]:
    """Resolve each result's version once, however many clauses came from it."""
    wanted = {(returned.document_slug, returned.version_label) for returned in results}
    if not wanted:
        return {}

    rows = session.execute(
        select(Document.slug, DocumentVersion.version_label, DocumentVersion.id)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(Document.slug.in_({slug for slug, _ in wanted}))
    ).all()
    return {
        (slug, label): version_id for slug, label, version_id in rows if (slug, label) in wanted
    }


def purge_expired(
    session: Session, *, retention_days: int | None, actor: Actor, now: datetime | None = None
) -> int:
    """Delete the questions asked more than `retention_days` ago, and record that it happened.

    Without a retention nothing is deleted. A retention counts from the day each
    question was asked, so a new one applies to every question kept, not only to the
    ones asked after it. Nothing is recorded when nothing was deleted: a daily entry
    saying no rows went would bury the ones that matter.
    """
    if retention_days is None:
        return 0
    session.execute(select(func.pg_advisory_xact_lock(PURGE_LOCK)))

    now = now or datetime.now(UTC)
    asked_before = now - timedelta(days=retention_days)
    # The ORM's delete() returns a CursorResult here; the cast is for the type
    # checker, which only knows the general Result.
    outcome = cast(
        "CursorResult[Any]",
        session.execute(delete(QueryLogEntry).where(QueryLogEntry.created_at < asked_before)),
    )
    deleted = outcome.rowcount
    if not deleted:
        return 0

    record(
        session,
        actor=actor,
        action=QUERY_LOG_PURGED,
        target_type="query_log",
        target_id=now.date().isoformat(),
        details={"deleted": int(deleted)},
    )
    return int(deleted)


def count_entries(session: Session) -> int:
    """How many questions are currently kept. For an operator, not for a screen."""
    return int(session.scalar(select(func.count()).select_from(QueryLogEntry)) or 0)
