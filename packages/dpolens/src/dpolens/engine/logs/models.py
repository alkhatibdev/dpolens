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

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, LargeBinary, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dpolens.engine.base import Base


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
