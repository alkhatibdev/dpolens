"""Personal access tokens, and the foreign key the governance log was waiting for

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        # SHA-256 hex of the token. A 256-bit random secret has no low-entropy
        # guess for a slow hash to defend against, and the lookup by digest is
        # the comparison.
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.String(50)), nullable=False),
        sa.Column("trusted_surface", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_personal_access_tokens_prefix", "personal_access_tokens", ["prefix"])
    op.create_index("ix_personal_access_tokens_owner", "personal_access_tokens", ["user_id"])

    # The column has been in the governance log's hash since the log existed,
    # because adding a hashed field later would mean a second recipe. This is
    # the table it was always meant to point at.
    op.create_foreign_key(
        "governance_log_actor_pat_id_fkey",
        "governance_log",
        "personal_access_tokens",
        ["actor_pat_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("governance_log_actor_pat_id_fkey", "governance_log", type_="foreignkey")
    op.drop_index("ix_personal_access_tokens_owner", table_name="personal_access_tokens")
    op.drop_index("ix_personal_access_tokens_prefix", table_name="personal_access_tokens")
    op.drop_table("personal_access_tokens")
