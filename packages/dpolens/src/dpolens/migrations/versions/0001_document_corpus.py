"""The document corpus, with published versions made immutable in the database

Revision ID: 0001
Revises:
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A citation is worthless if the text it points at can change underneath it.
# Application code could promise that; a trigger keeps the promise even when a
# future feature, a migration or a person with psql gets it wrong.
IMMUTABILITY = """
CREATE OR REPLACE FUNCTION reject_published_change() RETURNS trigger AS $$
DECLARE
    version_status text;
BEGIN
    IF TG_TABLE_NAME = 'document_versions' THEN
        version_status := OLD.status;
    ELSIF TG_TABLE_NAME = 'document_nodes' THEN
        SELECT status INTO version_status FROM document_versions
        WHERE id = OLD.document_version_id;
    ELSE
        SELECT v.status INTO version_status FROM document_versions v
        JOIN document_nodes n ON n.document_version_id = v.id
        WHERE n.id = OLD.node_id;
    END IF;

    IF version_status = 'published' THEN
        RAISE EXCEPTION
            'published document versions are immutable: % on %', TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- A BEFORE UPDATE trigger returning OLD would discard the change without
    -- saying so, which is worse than refusing it.
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

GUARDED_TABLES = ("document_versions", "document_nodes", "node_texts")


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.Enum("law", "org_policy", name="document_kind"), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="document_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "published", "discarded", name="version_status"),
            nullable=False,
        ),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source_ref", sa.String(200), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("document_id", "version_number"),
        sa.UniqueConstraint("document_id", "source_ref"),
    )
    # Search resolves the version in force by date, for laws and organisation
    # policies alike, so these two columns are read together on every query.
    op.create_index(
        "ix_document_versions_in_force",
        "document_versions",
        ["document_id", "effective_date"],
        postgresql_where=sa.text("status = 'published'"),
    )

    op.create_table(
        "document_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "parent_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_nodes.id"),
            nullable=True,
        ),
        sa.Column("canonical_key", sa.String(200), nullable=False),
        sa.Column("node_type", sa.String(40), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("is_normative", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.UniqueConstraint("document_version_id", "canonical_key"),
    )
    op.create_index("ix_document_nodes_canonical_key", "document_nodes", ["canonical_key"])
    op.create_index("ix_document_nodes_parent", "document_nodes", ["parent_node_id"])

    op.create_table(
        "node_texts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_nodes.id"),
            nullable=False,
        ),
        sa.Column("lang", sa.String(20), nullable=False),
        sa.Column("is_authoritative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "translation_status",
            sa.Enum(
                "original",
                "official_translation",
                "unofficial_translation",
                name="translation_status",
            ),
            nullable=False,
        ),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.UniqueConstraint("node_id", "lang"),
    )

    op.create_table(
        "node_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_nodes.id"),
            nullable=False,
        ),
        sa.Column("to_canonical_key", sa.String(200), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
    )
    op.create_index("ix_node_references_target", "node_references", ["to_canonical_key"])

    op.execute(IMMUTABILITY)
    for table in GUARDED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_are_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_published_change();
            """
        )


def downgrade() -> None:
    for table in GUARDED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_are_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_published_change()")

    op.drop_table("node_references")
    op.drop_table("node_texts")
    op.drop_table("document_nodes")
    op.drop_table("document_versions")
    op.drop_table("documents")

    for enum in ("translation_status", "version_status", "document_status", "document_kind"):
        op.execute(f"DROP TYPE IF EXISTS {enum}")
