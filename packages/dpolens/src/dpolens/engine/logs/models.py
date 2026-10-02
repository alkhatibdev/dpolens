"""The governance log's table.

`details` is `json` rather than `jsonb` on purpose: `json` stores the input text
exactly, and `jsonb` reorders keys and renormalises numbers, which would make a
hash over what the application wrote impossible to recompute from what comes
back out.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dpolens.engine.base import Base, uuid_pk


class GovernanceEntry(Base):
    """One governance action, hash-chained to the one before it.

    Nothing updates or deletes a row here: the privileges forbid it and triggers
    refuse it.
    """

    __tablename__ = "governance_log"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # No foreign key yet: the tokens table arrives in slice 2b. The column is
    # here from the start because it is inside the hash, and adding a hashed
    # field later would mean a second hash recipe.
    actor_pat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    entry_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    hash_version: Mapped[int] = mapped_column(SmallInteger)


SURFACES = ("dashboard", "mcp", "api", "slack", "github_action")
OPERATIONS = ("search", "get_clause", "get_subtree", "list_documents", "get_document", "ask")
STATUSES = ("ok", "no_match", "refused", "error")


class QueryLogEntry(Base):
    """One question asked of the corpus, redacted and with an expiry.

    The promise this table makes to a developer is that what they typed is stored
    redacted and deleted on a schedule. That is why the raw text has no column:
    there is nowhere for it to be kept by accident.
    """

    __tablename__ = "query_log_entries"

    id: Mapped[uuid.UUID] = uuid_pk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    actor_pat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_access_tokens.id"), nullable=True
    )
    surface: Mapped[str] = mapped_column(Enum(*SURFACES, name="query_surface"))
    operation: Mapped[str] = mapped_column(Enum(*OPERATIONS, name="query_operation"))
    query_redacted: Mapped[str] = mapped_column(Text, default="")
    """Empty for an operation that carries no question, such as reading a clause."""

    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The key or slug that was read, kept apart from the words somebody typed."""

    answer_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    redaction_count: Mapped[int] = mapped_column(Integer, default=0)
    redaction_types: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    status: Mapped[str] = mapped_column(Enum(*STATUSES, name="query_status"))

    results: Mapped[list[QueryLogResult]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )


class QueryLogResult(Base):
    """What one question returned, pointing at text rather than copying it.

    A published version never changes and is never deleted, so the version and the
    key together always resolve to exactly what was returned. Storing a snapshot
    of the text would be a second copy to keep honest.
    """

    __tablename__ = "query_log_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    query_log_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("query_log_entries.id", ondelete="CASCADE")
    )
    rank: Mapped[int] = mapped_column(Integer)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id")
    )
    canonical_key: Mapped[str] = mapped_column(String(200))
    lang: Mapped[str] = mapped_column(String(20))
    trust_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)

    entry: Mapped[QueryLogEntry] = relationship(back_populates="results")
