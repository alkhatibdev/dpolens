"""Fixing what was read: what a reviewer did to a clause, and the fix a flag suggests

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_nodes", sa.Column("fixed", sa.String(20), nullable=True))
    op.add_column("parse_flags", sa.Column("resolution_key", sa.String(200), nullable=True))
    op.add_column("parse_flags", sa.Column("suggestion", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("parse_flags", "suggestion")
    op.drop_column("parse_flags", "resolution_key")
    op.drop_column("document_nodes", "fixed")
