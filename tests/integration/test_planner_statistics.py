"""Setup gathers the query planner's statistics, which autovacuum leaves out for a small table."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from dpolens.cli.main import app
from dpolens.engine.session import gather_statistics

pytestmark = pytest.mark.integration

PACKS = Path(__file__).parent.parent / "fixtures" / "packs"


def analysed(owner_url: str, table: str) -> tuple[bool, float]:
    """Whether a table has been analysed, and how many rows the planner then expects."""
    engine = create_engine(owner_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT s.last_analyze IS NOT NULL, c.reltuples
                    FROM pg_stat_user_tables s JOIN pg_class c ON c.oid = s.relid
                    WHERE s.relname = :table
                    """
                ),
                {"table": table},
            ).one()
            return bool(row[0]), float(row[1])
    finally:
        engine.dispose()


def test_a_small_table_autovacuum_never_analyses_is_analysed(
    database_of_its_own: Callable[[str], tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app_url, owner_url = database_of_its_own(f"dpolens_statistics_{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("DPOLENS_DATABASE_URL", app_url)
    loaded = CliRunner().invoke(app, ["pack", "load", str(PACKS / "testlaw")])
    assert loaded.exit_code == 0, loaded.output
    assert not analysed(owner_url, "document_versions")[0]

    # As setup runs it, with the owner's URL beside the application's.
    monkeypatch.setenv("DPOLENS_MIGRATION_DATABASE_URL", owner_url)
    gather_statistics()

    # The test law's two documents, one version each.
    assert analysed(owner_url, "document_versions") == (True, 2.0)
