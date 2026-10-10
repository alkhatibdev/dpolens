"""A label for each language of a clause, so a translation is numbered in its own words

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Null where a clause's label is its node's, which is every text loaded
    # before a pack could carry a translation.
    op.add_column("node_texts", sa.Column("label", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("node_texts", "label")
