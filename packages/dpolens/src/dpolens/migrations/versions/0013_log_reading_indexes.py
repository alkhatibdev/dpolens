"""Indexes for reading the query log by time and by clause

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pages of the log, newest first, and every count over a window of days.
    op.create_index("ix_query_log_entries_created", "query_log_entries", ["created_at", "id"])
    # How often one clause was returned, for "Cited this week" on its page.
    op.create_index("ix_query_log_results_key", "query_log_results", ["canonical_key", "rank"])


def downgrade() -> None:
    op.drop_index("ix_query_log_results_key", table_name="query_log_results")
    op.drop_index("ix_query_log_entries_created", table_name="query_log_entries")
