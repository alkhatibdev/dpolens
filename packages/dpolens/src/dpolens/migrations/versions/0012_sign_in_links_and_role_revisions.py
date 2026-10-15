"""Sign-in links, and the revision a role is edited against

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sign_in_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_sign_in_links_user_id", "sign_in_links", ["user_id"])

    op.add_column("roles", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column(
        "roles",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column(
        "roles",
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.execute("UPDATE roles SET updated_at = created_at")


def downgrade() -> None:
    op.drop_column("roles", "updated_by_user_id")
    op.drop_column("roles", "updated_at")
    op.drop_column("roles", "revision")
    op.drop_index("ix_sign_in_links_user_id", "sign_in_links")
    op.drop_table("sign_in_links")
