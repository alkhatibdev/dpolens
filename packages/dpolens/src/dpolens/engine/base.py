"""The declarative base and the column helpers every table shares.

One metadata object, so `alembic upgrade head` sees every table and no subject
has to import another subject's models just to get a `Base`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
