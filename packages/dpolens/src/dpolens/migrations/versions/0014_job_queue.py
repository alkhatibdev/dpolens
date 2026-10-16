"""The job queue: Procrastinate's schema, as its version 3.10.0 ships it

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = Path(__file__).with_name("0014_procrastinate_3_10_0.sql")
"""Procrastinate 3.10.0's `procrastinate/sql/schema.sql`, with its licence at the top and one
comment's punctuation changed, so a new database gets exactly the schema the worker was tested
against, whatever version is installed later. Upgrading Procrastinate is a new revision that
runs the migration files it ships."""


def run(sql: str) -> None:
    """Hand SQL to the driver with no parameters at all, so its percent signs stay text and
    its many statements go in one call."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def upgrade() -> None:
    run(SCHEMA.read_text())


def downgrade() -> None:
    run(
        """
        DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers,
            procrastinate_jobs, procrastinate_workers CASCADE;
        DO $$
        DECLARE
            found record;
        BEGIN
            FOR found IN
                SELECT p.oid::regprocedure AS signature FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate%'
            LOOP
                EXECUTE 'DROP FUNCTION IF EXISTS ' || found.signature || ' CASCADE';
            END LOOP;
        END;
        $$;
        DROP TYPE IF EXISTS procrastinate_job_to_defer_v1, procrastinate_job_event_type,
            procrastinate_job_status CASCADE;
        """
    )
