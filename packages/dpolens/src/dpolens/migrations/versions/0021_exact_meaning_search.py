"""Meaning search compares every vector, so the approximate indexes go

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `dpolens index build` made one for each embedding model, named after the model. Whether
    # a search went through it or compared every vector was the planner's choice, made from
    # statistics that change as rows arrive, and the two do not return the same clauses.
    op.execute(
        """
        DO $$
        DECLARE
            approximate record;
        BEGIN
            FOR approximate IN
                SELECT built.relname AS name
                FROM pg_index
                JOIN pg_class AS built ON built.oid = pg_index.indexrelid
                JOIN pg_class AS held ON held.oid = pg_index.indrelid
                JOIN pg_namespace ON pg_namespace.oid = held.relnamespace
                JOIN pg_am ON pg_am.oid = built.relam
                WHERE held.relname = 'node_embeddings'
                  AND pg_namespace.nspname = current_schema()
                  AND pg_am.amname = 'hnsw'
            LOOP
                EXECUTE format('DROP INDEX %I', approximate.name);
            END LOOP;
        END
        $$
        """
    )


def downgrade() -> None:
    """Nothing to put back: the version before this one builds its index again when
    `dpolens index build` next runs, which is at every start, and searches without it until
    then."""
