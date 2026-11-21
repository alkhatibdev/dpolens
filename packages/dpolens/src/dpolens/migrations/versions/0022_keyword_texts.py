"""A law's clauses with their search questions' words, for keyword search

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The text search configurations of the law's own indexes: English stemmed, and Arabic folded by
# arabic_light, then stemmed.
INDEXES = {"en": ("words", "english"), "ar": ("words_ar", "arabic")}


def upgrade() -> None:
    # Each worded text of a law, with its clause's current search questions in that language
    # after it when it is the text in force. A clause with questions in a language it has no
    # words in has a row of questions alone, which is how an Arabic question finds a law
    # written in English by keyword. Written whole whenever the questions or a law change, from
    # what those tables hold, so nothing here is kept for its own sake.
    op.create_table(
        "keyword_texts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_text_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("node_texts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("lang", sa.String(20), nullable=False),
        sa.Column("words", sa.Text(), nullable=False),
        sa.Column(
            "words_ar",
            sa.Text(),
            sa.Computed("CASE WHEN lang = 'ar' THEN arabic_light(words) END", persisted=True),
        ),
    )
    for lang, (column, text_config) in INDEXES.items():
        op.execute(
            f"""
            CREATE INDEX keyword_texts_bm25_{lang} ON keyword_texts
            USING bm25({column}) WITH (text_config='{text_config}')
            WHERE lang = '{lang}'
            """
        )

    # Emptied with TRUNCATE before it is written again. A BM25 index keeps counting a deleted
    # row in its statistics, so rows deleted and written again would not score as the same rows
    # written once, and a search would drift with every rewrite.
    app_role = context.config.attributes.get("app_role")
    current = op.get_bind().exec_driver_sql("SELECT current_user").scalar_one()
    if app_role and app_role != current:
        role = '"' + app_role.replace('"', '""') + '"'
        op.execute(f"GRANT TRUNCATE ON keyword_texts TO {role}")


def downgrade() -> None:
    for lang in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS keyword_texts_bm25_{lang}")
    op.drop_table("keyword_texts")
