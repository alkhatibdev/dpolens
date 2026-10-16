"""The document corpus: laws and organisation policies in one shape.

Search, the library, citations and diffs treat both the same way, which is why
they share these tables. A citation is a document version plus a canonical key,
and a published version never changes, so a citation always resolves to the
exact text that was returned.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dpolens.engine.base import Base
from dpolens.engine.packs.models import Pack


def _uuid_column() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_column()
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Null for an organisation's own policy, which is its own source.
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Enum("law", "org_policy", name="document_kind"))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum("active", "archived", name="document_status"), default="active"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[list[DocumentVersion]] = relationship(back_populates="document")
    # Joined, because every result a reader sees carries the pack's trust tier
    # and where the text came from.
    pack: Mapped[Pack | None] = relationship(lazy="joined")


class DocumentVersion(Base):
    """One fixed state of a document's text.

    The version in force is the latest published one whose effective date has
    passed. A published version dated later is scheduled: visible in the
    library, and not returned by search.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number"),
        UniqueConstraint("document_id", "source_ref"),
    )

    id: Mapped[uuid.UUID] = _uuid_column()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    version_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("draft", "published", "discarded", name="version_status")
    )
    effective_date: Mapped[date] = mapped_column(Date)
    source_ref: Mapped[str] = mapped_column(String(200))
    """Where this version came from, such as pack:gdpr@2026.1. Makes a load idempotent."""

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # The rest is an uploaded policy's, and empty for a pack's version.
    source_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    """Where the original file is kept: a key from its SHA-256, never a path."""
    source_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parse_checks: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    """What the parser found: coverage, what it set aside, and anything the file itself said."""
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    index_job_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """The job that embeds this version once published, for showing whether it has run."""
    reading: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    """The file as it was read: every paragraph in order, with its place and its type. Kept, so
    that a later reader finding more in the same file never moves this version's paragraphs."""

    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    """Goes up with every change to a draft, so a change made against an older one is refused
    rather than undoing somebody else's."""
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    document: Mapped[Document] = relationship(back_populates="versions")
    nodes: Mapped[list[DocumentNode]] = relationship(back_populates="version")
    flags: Mapped[list[ParseFlag]] = relationship(back_populates="version")


class DocumentNode(Base):
    """One clause, belonging to one version.

    The row's id is per version; the canonical key is what carries across
    versions and what citations point at.
    """

    __tablename__ = "document_nodes"
    __table_args__ = (UniqueConstraint("document_version_id", "canonical_key"),)

    id: Mapped[uuid.UUID] = _uuid_column()
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_nodes.id"), nullable=True
    )
    canonical_key: Mapped[str] = mapped_column(String(200), index=True)
    node_type: Mapped[str] = mapped_column(String(40))
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """The numbering the law itself uses, such as 1. or (a)."""

    is_normative: Mapped[bool] = mapped_column(Boolean, default=True)
    """False for text that explains without obliging, such as a recital."""

    order_index: Mapped[int] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer)

    parse_layer: Mapped[str | None] = mapped_column(String(30), nullable=True)
    """Which layer of the parser decided this clause; empty for a pack's."""
    source_anchor: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    """Where in the original file the clause's paragraphs are."""
    previous_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_nodes.id"), nullable=True
    )
    """The clause this one continues in the previous version, matched by key and by text."""
    change_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    """added, modified, moved or unchanged against the previous version; empty for the first."""

    version: Mapped[DocumentVersion] = relationship(back_populates="nodes")
    texts: Mapped[list[NodeText]] = relationship(back_populates="node")
    references: Mapped[list[NodeReference]] = relationship(back_populates="node")


class NodeText(Base):
    """A clause's text in one language.

    A clause can hold several: an authoritative original and its official
    translations, all under the same key.
    """

    __tablename__ = "node_texts"
    __table_args__ = (UniqueConstraint("node_id", "lang"),)

    id: Mapped[uuid.UUID] = _uuid_column()
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_nodes.id"))
    lang: Mapped[str] = mapped_column(String(20))
    is_authoritative: Mapped[bool] = mapped_column(Boolean, default=False)
    translation_status: Mapped[str] = mapped_column(
        Enum(
            "original",
            "official_translation",
            "unofficial_translation",
            name="translation_status",
        )
    )
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The numbering in this language, such as Article (4) beside المادة (4)."""
    body_text: Mapped[str] = mapped_column(Text)
    """Verbatim. This is what citations quote and what verification checks against."""

    search_text: Mapped[str] = mapped_column(
        Text, Computed("coalesce(heading, '') || ' ' || body_text")
    )
    """Heading and text together, which is what the BM25 index ranks."""

    search_text_ar: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            "CASE WHEN lang = 'ar' THEN arabic_light(coalesce(heading, '') || ' ' || body_text) END"
        ),
    )
    """An Arabic text with its spellings folded and its articles off, for the Arabic index."""

    node: Mapped[DocumentNode] = relationship(back_populates="texts")


class NodeReference(Base):
    """A pointer one clause makes to another, as the text itself writes it."""

    __tablename__ = "node_references"

    id: Mapped[uuid.UUID] = _uuid_column()
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_nodes.id"))
    to_canonical_key: Mapped[str] = mapped_column(String(200), index=True)
    raw_text: Mapped[str] = mapped_column(Text)

    node: Mapped[DocumentNode] = relationship(back_populates="references")


class ParseFlag(Base):
    """One thing in a draft the parser could not settle, for a reviewer to resolve or accept."""

    __tablename__ = "parse_flags"
    __table_args__ = (UniqueConstraint("document_version_id", "position"),)

    id: Mapped[uuid.UUID] = _uuid_column()
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_nodes.id"), nullable=True
    )
    canonical_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    """Its place in the draft's list of flags, which is how a reviewer names one."""

    paragraph: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """The paragraph of the file it is about, when it is about one."""

    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """What a reviewer changed that settled it, such as match-rejected. A flag is settled once
    it is accepted as read or resolved by a change."""

    version: Mapped[DocumentVersion] = relationship(back_populates="flags")
