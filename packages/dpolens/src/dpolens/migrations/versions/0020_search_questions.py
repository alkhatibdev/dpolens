"""Search questions beside the clauses they were written for, and the switch that turns them off

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # What a law's file said when it was loaded: who wrote and checked its questions, when,
    # with which prompts, and the file's own digest, so loading the same file again is a no-op.
    op.create_table(
        "search_question_files",
        sa.Column(
            "pack_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("packs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("written_by", sa.Text(), nullable=False),
        sa.Column("checked_by", sa.Text(), nullable=False),
        sa.Column("written_on", sa.Date(), nullable=False),
        sa.Column("write_prompt", sa.String(16), nullable=False),
        sa.Column("check_prompt", sa.String(16), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "search_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pack_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("search_question_files.pack_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        # The words the question was written for. Where a clause's words in force no longer
        # match them, `current` is false and the question is not used.
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lang", sa.String(20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
    )
    op.create_index("search_questions_by_key", "search_questions", ["canonical_key"])
    op.create_table(
        "search_question_embeddings",
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("search_questions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "embedding_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("embedding_models.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Untyped, as a clause's vectors are, so models of different sizes can coexist.
        sa.Column("embedding", postgresql.ARRAY(sa.REAL()), nullable=False),
    )
    op.execute(
        "ALTER TABLE search_question_embeddings ALTER COLUMN embedding TYPE vector "
        "USING embedding::vector"
    )
    # One row, as `instance` is: whether this organisation's searches use the questions.
    op.create_table(
        "search_settings",
        sa.Column("singleton", sa.Boolean(), primary_key=True, server_default=sa.true()),
        sa.Column("questions", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("singleton", name="search_settings_one_row"),
    )
    op.execute("INSERT INTO search_settings (singleton, questions) VALUES (true, true)")


def downgrade() -> None:
    op.drop_table("search_settings")
    op.drop_table("search_question_embeddings")
    op.drop_index("search_questions_by_key", table_name="search_questions")
    op.drop_table("search_questions")
    op.drop_table("search_question_files")
