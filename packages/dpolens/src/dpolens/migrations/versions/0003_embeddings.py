"""Vectors for clause text, tagged with the model and recipe that made them

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "embedding_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # One model answers queries at a time. Mixing vectors from two models in one
    # search compares numbers that mean different things.
    op.create_index(
        "embedding_models_one_active",
        "embedding_models",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "node_embeddings",
        sa.Column(
            "node_text_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("node_texts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "embedding_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("embedding_models.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("context_recipe", sa.String(20), nullable=False),
        # What the model actually saw. Stored so that "why did this match" can be
        # answered by reading, and so a recipe change is a visible diff.
        sa.Column("embedded_string", sa.Text(), nullable=False),
        # Untyped on purpose: models of different sizes coexist while an
        # instance re-indexes, and each gets its own index at the right width.
        sa.Column("embedding", postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute(
        "ALTER TABLE node_embeddings ALTER COLUMN embedding TYPE vector USING embedding::vector"
    )


def downgrade() -> None:
    op.drop_table("node_embeddings")
    op.drop_index("embedding_models_one_active", table_name="embedding_models")
    op.drop_table("embedding_models")
