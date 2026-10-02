"""The query log: what was asked, redacted, and when it expires

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "query_log_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Indexed because the only query that runs against the whole table is the
        # purge, which asks what has expired.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "actor_pat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("personal_access_tokens.id"),
            nullable=True,
        ),
        sa.Column(
            "surface",
            sa.Enum("dashboard", "mcp", "api", "slack", "github_action", name="query_surface"),
            nullable=False,
        ),
        sa.Column(
            "operation",
            sa.Enum(
                "search",
                "get_clause",
                "get_subtree",
                "list_documents",
                "get_document",
                "ask",
                name="query_operation",
            ),
            nullable=False,
        ),
        # There is no column for the raw question, so there is nowhere for it to
        # be kept by accident.
        sa.Column("query_redacted", sa.Text(), nullable=False, server_default=""),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("answer_redacted", sa.Text(), nullable=True),
        sa.Column("redaction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "redaction_types",
            postgresql.ARRAY(sa.String(50)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "status",
            sa.Enum("ok", "no_match", "refused", "error", name="query_status"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_query_log_entries_actor", "query_log_entries", ["actor_user_id", "created_at"]
    )

    op.create_table(
        "query_log_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "query_log_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("query_log_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column("canonical_key", sa.String(200), nullable=False),
        sa.Column("lang", sa.String(20), nullable=False),
        sa.Column("trust_tier", sa.String(20), nullable=True),
    )
    op.create_index(
        "ix_query_log_results_entry", "query_log_results", ["query_log_entry_id", "rank"]
    )


def downgrade() -> None:
    op.drop_index("ix_query_log_results_entry", table_name="query_log_results")
    op.drop_table("query_log_results")
    op.drop_index("ix_query_log_entries_actor", table_name="query_log_entries")
    op.drop_table("query_log_entries")
    for enum in ("query_status", "query_operation", "query_surface"):
        op.execute(f"DROP TYPE IF EXISTS {enum}")
