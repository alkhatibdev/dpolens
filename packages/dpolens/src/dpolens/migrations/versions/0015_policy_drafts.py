"""Policy drafts: the original file, what the parser found, and the flags a reviewer settles

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A published version's flags record who accepted what. They are as fixed as its clauses.
FLAG_IMMUTABILITY = """
CREATE OR REPLACE FUNCTION reject_published_flag_change() RETURNS trigger AS $$
BEGIN
    IF (SELECT status FROM document_versions WHERE id = OLD.document_version_id) = 'published'
    THEN
        RAISE EXCEPTION 'published document versions are immutable: % on parse_flags', TG_OP
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    users = sa.ForeignKey("users.id")
    op.add_column("document_versions", sa.Column("source_key", sa.String(120), nullable=True))
    op.add_column("document_versions", sa.Column("source_name", sa.Text(), nullable=True))
    op.add_column("document_versions", sa.Column("source_size", sa.BigInteger(), nullable=True))
    op.add_column("document_versions", sa.Column("source_sha256", sa.String(64), nullable=True))
    op.add_column("document_versions", sa.Column("source_format", sa.String(20), nullable=True))
    op.add_column(
        "document_versions",
        sa.Column("parse_checks", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), users, nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column(
            "published_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column("document_versions", sa.Column("index_job_id", sa.BigInteger(), nullable=True))
    # One open draft per document: a second upload replaces it or waits.
    op.create_index(
        "ux_document_versions_one_draft",
        "document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )

    op.add_column("document_nodes", sa.Column("parse_layer", sa.String(30), nullable=True))
    op.add_column("document_nodes", sa.Column("source_anchor", postgresql.JSONB(), nullable=True))
    op.add_column(
        "document_nodes",
        sa.Column(
            "previous_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_nodes.id"),
            nullable=True,
        ),
    )
    op.add_column("document_nodes", sa.Column("change_type", sa.String(20), nullable=True))
    op.create_index("ix_document_nodes_previous", "document_nodes", ["previous_node_id"])

    op.create_table(
        "parse_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_nodes.id"),
            nullable=True,
        ),
        sa.Column("canonical_key", sa.String(200), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "accepted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("document_version_id", "position"),
    )
    op.execute(FLAG_IMMUTABILITY)
    op.execute(
        "CREATE TRIGGER parse_flags_are_immutable_once_published "
        "BEFORE UPDATE OR DELETE ON parse_flags "
        "FOR EACH ROW EXECUTE FUNCTION reject_published_flag_change()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS parse_flags_are_immutable_once_published ON parse_flags")
    op.execute("DROP FUNCTION IF EXISTS reject_published_flag_change()")
    op.drop_table("parse_flags")
    op.drop_index("ix_document_nodes_previous", table_name="document_nodes")
    for column in ("change_type", "previous_node_id", "source_anchor", "parse_layer"):
        op.drop_column("document_nodes", column)
    op.drop_index("ux_document_versions_one_draft", table_name="document_versions")
    for column in (
        "index_job_id",
        "published_by_user_id",
        "created_by_user_id",
        "parse_checks",
        "source_format",
        "source_sha256",
        "source_size",
        "source_name",
        "source_key",
    ):
        op.drop_column("document_versions", column)
