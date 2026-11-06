"""What a pack is, once it has been loaded.

The pack file carries the things that make a citation checkable: which law it is,
whose law it is, where the text came from, what licence it arrives under, and
whether a named maintainer has read it against the official source. Until this
table existed those fields were read at load time and thrown away, so a result
could not say any of it.

One row per pack slug, holding the version currently loaded, and its names in each
language the pack names it in: a law written in Arabic first is named in Arabic beside
its Arabic text, and in English on an English screen.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dpolens.engine.base import Base, uuid_pk

TRUST_TIERS = ("verified", "community")


class Pack(Base):
    __tablename__ = "packs"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    region: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """Where the law is listed. Empty only for a pack loaded before packs said."""
    version: Mapped[str] = mapped_column(String(50))
    effective_date: Mapped[date] = mapped_column(Date)
    trust_tier: Mapped[str] = mapped_column(Enum(*TRUST_TIERS, name="trust_tier"))
    source_url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    authoritative_language: Mapped[str] = mapped_column(String(20))
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Loaded with the pack, because nearly everything that reads a pack names it.
    names: Mapped[list[PackName]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="PackName.lang"
    )

    def named_in(self, lang: str | None) -> PackName:
        """The law's names in `lang`, or else in English, which every pack has."""
        by_lang = {names.lang: names for names in self.names}
        return by_lang.get(lang or "en") or by_lang.get("en") or self.names[0]


class PackName(Base):
    """A law's names in one language: as its official text names it, as people call it, and
    where it applies."""

    __tablename__ = "pack_names"

    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id"), primary_key=True
    )
    lang: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    """The official name: the law's number and the short title it gives itself, where it gives
    one, else its title as printed."""
    short_name: Mapped[str] = mapped_column(Text)
    jurisdiction: Mapped[str] = mapped_column(Text)


class SelectedLaw(Base):
    """A law the organisation has said applies to it. No rows means none chosen yet."""

    __tablename__ = "selected_laws"

    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packs.id"), primary_key=True
    )
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
