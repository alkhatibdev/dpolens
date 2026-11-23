"""What a search showed beneath each whole rule it returned

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A search result is a whole rule: its own words and the clauses beneath them. The key and
    # version name the rule; these keys name what was shown of it, which for a long rule is only
    # the two clauses the search ranked highest, so the log still says exactly what came back.
    # A result logged before this held one clause and nothing beneath it.
    op.add_column(
        "query_log_results",
        sa.Column(
            "beneath",
            postgresql.ARRAY(sa.String(200)),
            nullable=False,
            server_default="{}",
        ),
    )
    # A clause's activity counts the searches that showed it beneath the rule that came first.
    op.create_index(
        "ix_query_log_results_beneath",
        "query_log_results",
        ["beneath"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_query_log_results_beneath", table_name="query_log_results")
    op.drop_column("query_log_results", "beneath")
