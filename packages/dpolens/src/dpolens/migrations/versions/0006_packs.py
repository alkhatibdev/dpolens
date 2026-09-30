"""The pack a document came from, so a citation can carry its trust tier

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "packs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        # What a reader is told about how far the text has been checked: reviewed
        # against the official source by a named maintainer, or passed CI only.
        sa.Column(
            "trust_tier",
            sa.Enum("verified", "community", name="trust_tier"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("authoritative_language", sa.String(20), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    # Null for an organisation's own policy, which is its own source and carries
    # no trust tier.
    op.add_column(
        "documents",
        sa.Column(
            "pack_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("packs.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_pack", "documents", ["pack_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_pack", table_name="documents")
    op.drop_column("documents", "pack_id")
    op.drop_table("packs")
    op.execute("DROP TYPE IF EXISTS trust_tier")
