"""Retrieval extensions, and a BM25 index over clause text

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One index per language, because a BM25 index fixes its text search
# configuration at creation. A query names the index it wants, which is what
# keeps an English question off Arabic rows and the other way round.
LANGUAGES = {"en": "english"}


def upgrade() -> None:
    # Both halves of retrieval are extensions, and an instance without them
    # cannot rank properly, so they are created here rather than by hand.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")

    # A clause is findable by its heading as well as its text. Article 17 holds
    # no text of its own, and "right to erasure" is exactly what someone types.
    op.execute(
        """
        ALTER TABLE node_texts ADD COLUMN search_text text
        GENERATED ALWAYS AS (coalesce(heading, '') || ' ' || body_text) STORED
        """
    )

    for lang, text_config in LANGUAGES.items():
        op.execute(
            f"""
            CREATE INDEX node_texts_bm25_{lang} ON node_texts
            USING bm25(search_text) WITH (text_config='{text_config}')
            WHERE lang = '{lang}'
            """
        )


def downgrade() -> None:
    for lang in LANGUAGES:
        op.execute(f"DROP INDEX IF EXISTS node_texts_bm25_{lang}")
    op.execute("ALTER TABLE node_texts DROP COLUMN IF EXISTS search_text")
    op.execute("DROP EXTENSION IF EXISTS pg_textsearch")
    op.execute("DROP EXTENSION IF EXISTS vector")
