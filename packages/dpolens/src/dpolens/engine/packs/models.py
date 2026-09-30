"""What a pack is, once it has been loaded.

The pack file carries the things that make a citation checkable: which law it is,
whose law it is, where the text came from, what licence it arrives under, and
whether a named maintainer has read it against the official source. Until this
table existed those fields were read at load time and thrown away, so a result
could not say any of it.

One row per pack slug, holding the version currently loaded. Keeping several
versions of a pack at once is what the update command will need, and it can have
its own table when it exists.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from dpolens.engine.base import Base, uuid_pk

TRUST_TIERS = ("verified", "community")


class Pack(Base):
    __tablename__ = "packs"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(Text)
    jurisdiction: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(50))
    effective_date: Mapped[date] = mapped_column(Date)
    trust_tier: Mapped[str] = mapped_column(Enum(*TRUST_TIERS, name="trust_tier"))
    source_url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    authoritative_language: Mapped[str] = mapped_column(String(20))
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
