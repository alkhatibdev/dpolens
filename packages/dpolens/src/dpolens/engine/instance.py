"""This instance's own identity: one row, and nothing points at it.

It exists for two reasons. A governance export has to name the instance it came
from, so an auditor holding two exports can tell them apart. And the first link
of the governance chain is built from this id, so a chain from one instance
cannot be presented as another's.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from dpolens.engine.base import Base


class MissingInstanceRow(Exception):
    """The instance row is absent, so this database was never migrated properly."""


class Instance(Base):
    """One row, guarded by a unique constraint on a column that can only be true."""

    __tablename__ = "instance"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    singleton: Mapped[bool] = mapped_column(Boolean, unique=True, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def instance_id(session: Session) -> uuid.UUID:
    """The id of this instance, written once by the migration that created it."""
    found = session.scalars(select(Instance.id)).all()
    if len(found) != 1:
        raise MissingInstanceRow(
            f"expected exactly one row in `instance`, found {len(found)}. "
            "Run `alembic upgrade head` against this database."
        )
    return found[0]
