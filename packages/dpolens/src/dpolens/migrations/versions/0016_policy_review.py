"""Reviewing a draft: its revision, the file as it was read, and flags a change settles

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A constant default fills existing rows without rewriting them, so no trigger fires.
    op.add_column(
        "document_versions",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "document_versions", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "document_versions",
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column("document_versions", sa.Column("reading", postgresql.JSONB(), nullable=True))

    op.add_column("parse_flags", sa.Column("paragraph", sa.Integer(), nullable=True))
    op.add_column(
        "parse_flags", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "parse_flags",
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column("parse_flags", sa.Column("resolution", sa.String(40), nullable=True))


def downgrade() -> None:
    for column in ("resolution", "resolved_by_user_id", "resolved_at", "paragraph"):
        op.drop_column("parse_flags", column)
    for column in ("reading", "updated_by_user_id", "updated_at", "revision"):
        op.drop_column("document_versions", column)
