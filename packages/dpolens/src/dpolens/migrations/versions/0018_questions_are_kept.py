"""Questions are kept: a retention, when one is set, counts from the day a question was asked

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Each question's deletion date was fixed when it was stored. Questions are now kept
    # unless an operator sets a retention, which counts from the day each was asked, so
    # there is no date to store. Dropping the column drops its index.
    op.drop_column("query_log_entries", "expires_at")


def downgrade() -> None:
    op.add_column(
        "query_log_entries",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The default before this revision: 365 days from the day each question was asked.
    op.execute("UPDATE query_log_entries SET expires_at = created_at + interval '365 days'")
    op.alter_column("query_log_entries", "expires_at", nullable=False)
    op.create_index("ix_query_log_entries_expires_at", "query_log_entries", ["expires_at"])
