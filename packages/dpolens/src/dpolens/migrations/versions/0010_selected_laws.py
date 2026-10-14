"""Selected laws, and whether a logged search stayed inside them

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPE = postgresql.ENUM("selected", "other", name="query_scope", create_type=False)


def upgrade() -> None:
    # No rows means nobody has chosen yet, and every loaded law is searched.
    op.create_table(
        "selected_laws",
        sa.Column(
            "pack_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("packs.id"),
            primary_key=True,
        ),
        sa.Column(
            "selected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    # Null for an operation that is not a search, and for searches logged before.
    SCOPE.create(op.get_bind())
    op.add_column("query_log_entries", sa.Column("scope", SCOPE, nullable=True))


def downgrade() -> None:
    op.drop_column("query_log_entries", "scope")
    SCOPE.drop(op.get_bind())
    op.drop_table("selected_laws")
