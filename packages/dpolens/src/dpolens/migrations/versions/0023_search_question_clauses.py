"""Every clause a law's search questions were written for, including one left with none

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Each clause a law's file names, at the words its questions were written for. A clause
    # whose check kept none of its questions is here too, so a clause that states a rule and is
    # missing, or is here at other words, is one nobody has written questions for.
    op.create_table(
        "search_question_clauses",
        sa.Column(
            "pack_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("search_question_files.pack_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("canonical_key", sa.Text(), primary_key=True),
        sa.Column("fingerprint", sa.String(16), nullable=False),
    )
    # A file loaded before this table existed named no clause without questions, so its
    # clauses are the ones its questions sit beside.
    op.execute(
        """
        INSERT INTO search_question_clauses (pack_id, canonical_key, fingerprint)
        SELECT DISTINCT ON (pack_id, canonical_key) pack_id, canonical_key, fingerprint
        FROM search_questions
        ORDER BY pack_id, canonical_key, fingerprint
        """
    )


def downgrade() -> None:
    op.drop_table("search_question_clauses")
