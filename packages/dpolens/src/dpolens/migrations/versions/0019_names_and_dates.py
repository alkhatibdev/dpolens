"""A law named in each of its languages, and the days each text applies

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pack_names",
        sa.Column(
            "pack_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("packs.id"), primary_key=True
        ),
        sa.Column("lang", sa.String(20), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("short_name", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
    )
    # What a pack loaded before said, in English, until the instance loads the pack again:
    # setup loads every pack in the image, so the first start after an upgrade does.
    op.execute(
        """
        INSERT INTO pack_names (pack_id, lang, name, short_name, jurisdiction)
        SELECT id, 'en', name, upper(replace(slug, '-', ' ')), jurisdiction FROM packs
        """
    )
    op.add_column("packs", sa.Column("region", sa.String(40), nullable=True))
    op.drop_column("packs", "name")
    op.drop_column("packs", "jurisdiction")

    op.create_table(
        "document_titles",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            primary_key=True,
        ),
        sa.Column("lang", sa.String(20), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
    )
    # A law's title was English. A policy's is in the language most of its text is in.
    op.execute(
        """
        INSERT INTO document_titles (document_id, lang, title)
        SELECT d.id,
               CASE WHEN d.kind = 'law' THEN 'en' ELSE coalesce(
                   (SELECT t.lang
                    FROM node_texts t
                    JOIN document_nodes n ON n.id = t.node_id
                    JOIN document_versions v ON v.id = n.document_version_id
                    WHERE v.document_id = d.id
                    GROUP BY t.lang
                    ORDER BY count(*) DESC, t.lang
                    LIMIT 1),
                   'en') END,
               d.title
        FROM documents d
        """
    )
    op.drop_column("documents", "title")

    # A clause can now hold, in one language, the words in force and the words an amendment
    # gives it from a later day, so one text per language becomes one per language and day.
    op.add_column("node_texts", sa.Column("applies_from", sa.Date(), nullable=True))
    op.add_column("node_texts", sa.Column("applies_until", sa.Date(), nullable=True))
    op.add_column(
        "node_texts",
        sa.Column("pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("node_texts", sa.Column("dated_by", sa.Text(), nullable=True))
    op.drop_constraint("node_texts_node_id_lang_key", "node_texts", type_="unique")
    op.create_unique_constraint(
        "node_texts_node_id_lang_applies_from_key",
        "node_texts",
        ["node_id", "lang", "applies_from"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # Refused while a clause holds a later text in some language: one text per language
    # cannot hold both.
    op.drop_constraint("node_texts_node_id_lang_applies_from_key", "node_texts", type_="unique")
    op.create_unique_constraint("node_texts_node_id_lang_key", "node_texts", ["node_id", "lang"])
    for column in ("dated_by", "pending", "applies_until", "applies_from"):
        op.drop_column("node_texts", column)

    op.add_column("documents", sa.Column("title", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE documents d SET title = (
            SELECT title FROM document_titles t
            WHERE t.document_id = d.id
            ORDER BY t.lang = 'en' DESC, t.lang
            LIMIT 1
        )
        """
    )
    op.alter_column("documents", "title", nullable=False)
    op.drop_table("document_titles")

    op.add_column("packs", sa.Column("name", sa.Text(), nullable=True))
    op.add_column("packs", sa.Column("jurisdiction", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE packs p SET name = n.name, jurisdiction = n.jurisdiction
        FROM pack_names n WHERE n.pack_id = p.id AND n.lang = 'en'
        """
    )
    op.alter_column("packs", "name", nullable=False)
    op.alter_column("packs", "jurisdiction", nullable=False)
    op.drop_column("packs", "region")
    op.drop_table("pack_names")
