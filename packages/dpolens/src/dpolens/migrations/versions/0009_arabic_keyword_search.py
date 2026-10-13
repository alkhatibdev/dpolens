"""Keyword search over Arabic text, in three ways, so the evals can choose between them

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One letter for each family of spellings that change no word: the alef forms,
# alef maqsura and yeh, ta marbuta and heh, the hamza seats, the Persian forms of
# yeh and kaf, and Arabic-Indic digits.
FOLD_FROM = "أإآٱىةؤئیک٠١٢٣٤٥٦٧٨٩"
FOLD_TO = "اااايهءءيك0123456789"

# Light normalisation: fold the spellings, drop diacritics and the stretching
# stroke, and take the article off the front of a word, alone or after و, ف, ب,
# ك or ل, when at least two letters are left. Nothing else is stemmed, so a
# question's word and the law's word match when they are the same word, and only
# then. It is a function so that the index and every question go through the
# same steps; changing it means a new column, since a stored value is not
# recomputed.
ARABIC_LIGHT = f"""
CREATE OR REPLACE FUNCTION arabic_light(input text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $fn$
    SELECT coalesce(string_agg(
               CASE
                   WHEN token ~ '^(وال|فال|بال|كال)..' THEN substr(token, 4)
                   WHEN token ~ '^(ال|لل)..' THEN substr(token, 3)
                   ELSE token
               END, ' ' ORDER BY position), '')
    FROM regexp_split_to_table(
             translate(regexp_replace(input, '[\\u064B-\\u065F\\u0670\\u0640]', '', 'g'),
                       '{FOLD_FROM}', '{FOLD_TO}'),
             '[^0-9A-Za-z\\u0621-\\u064A]+') WITH ORDINALITY AS split(token, position)
    WHERE token <> ''
$fn$
"""


def upgrade() -> None:
    op.execute(ARABIC_LIGHT)

    # Generated, so every Arabic text already loaded gets it too: published
    # rows refuse an update, and adding the column rewrites the table instead.
    op.execute(
        """
        ALTER TABLE node_texts ADD COLUMN search_text_ar text
        GENERATED ALWAYS AS (
            CASE WHEN lang = 'ar'
                 THEN arabic_light(coalesce(heading, '') || ' ' || body_text)
            END
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX node_texts_bm25_ar ON node_texts
        USING bm25(search_text_ar) WITH (text_config='simple')
        WHERE lang = 'ar'
        """
    )

    # Postgres's own Arabic stemmer, beside the light normalisation for the evals
    # to compare. It cuts بيانات to يانا but البيانات to بيان, so a question and the
    # law can miss each other on the commonest word in the law.
    op.execute(
        """
        CREATE INDEX node_texts_bm25_ar_snowball ON node_texts
        USING bm25(search_text) WITH (text_config='arabic')
        WHERE lang = 'ar'
        """
    )

    # The stemmer again, after the light normalisation, so that a word reaches it
    # in one spelling and without its article, and both forms of it stem alike.
    op.execute(
        """
        CREATE INDEX node_texts_bm25_ar_folded_snowball ON node_texts
        USING bm25(search_text_ar) WITH (text_config='arabic')
        WHERE lang = 'ar'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS node_texts_bm25_ar_folded_snowball")
    op.execute("DROP INDEX IF EXISTS node_texts_bm25_ar_snowball")
    op.execute("DROP INDEX IF EXISTS node_texts_bm25_ar")
    op.execute("ALTER TABLE node_texts DROP COLUMN IF EXISTS search_text_ar")
    op.execute("DROP FUNCTION IF EXISTS arabic_light(text)")
