"""Users, roles and the permission lookup table.

A user is never deleted: the row is what a log entry points at, so attribution
survives someone leaving. Deactivation blocks access and keeps the row; erasure
clears the personal details and keeps the id, so the governance chain still
verifies.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Table, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dpolens.engine.base import Base, uuid_pk

KINDS = ("person", "service_account")
STATUSES = ("active", "deactivated", "erased")

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("permission_key", String(50), ForeignKey("permissions.key"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base):
    """One entry of the code catalog, mirrored so a role can reference it."""

    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    description: Mapped[str] = mapped_column(Text)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_seeded: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, lazy="selectin", order_by=Permission.key
    )

    def permission_keys(self) -> frozenset[str]:
        return frozenset(permission.key for permission in self.permissions)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    # Unset until the dashboard exists, and always unset for a service account.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(Enum(*KINDS, name="user_kind"), default="person")
    status: Mapped[str] = mapped_column(Enum(*STATUSES, name="user_status"), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, lazy="selectin", order_by=Role.name
    )

    def effective_permissions(self) -> frozenset[str]:
        """The union of this user's roles, and nothing at all if they cannot sign in.

        A deactivated account keeps its roles, so reactivating it restores what
        it had, and holds no permissions while it is deactivated.
        """
        if self.status != "active":
            return frozenset()
        keys: set[str] = set()
        for role in self.roles:
            keys |= role.permission_keys()
        return frozenset(keys)
