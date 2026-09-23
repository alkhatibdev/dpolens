"""The command line, against a real database.

This is the shape of step 1a: load the pack, print an article, read it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dpolens.cli.main import app

pytestmark = pytest.mark.integration

GDPR_PACK = Path(__file__).parents[2] / "packs" / "gdpr"
runner = CliRunner()


@pytest.fixture
def instance(migrated: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DPOLENS_DATABASE_URL", migrated)
    yield
    monkeypatch.delenv("DPOLENS_DATABASE_URL", raising=False)


@pytest.fixture
def loaded(instance: None, clean_tables: None) -> None:
    result = runner.invoke(app, ["pack", "load", str(GDPR_PACK)])
    assert result.exit_code == 0, result.output


def test_loading_a_pack_reports_what_it_did(instance: None, clean_tables: None) -> None:
    result = runner.invoke(app, ["pack", "load", str(GDPR_PACK)])

    assert result.exit_code == 0
    assert "Loaded gdpr 2026.1" in result.output
    assert "2 documents" in result.output


def test_loading_twice_is_a_no_op(loaded: None) -> None:
    result = runner.invoke(app, ["pack", "load", str(GDPR_PACK)])

    assert result.exit_code == 0
    assert "already loaded" in result.output


def test_showing_an_article(loaded: None) -> None:
    result = runner.invoke(app, ["clause", "show", "gdpr:art-17"])

    assert result.exit_code == 0
    assert "Article 17" in result.output
    assert "Right to erasure" in result.output
    assert "gdpr:art-17" in result.output
    assert "in force 2018-05-25" in result.output


def test_showing_a_subtree_prints_the_points(loaded: None) -> None:
    result = runner.invoke(app, ["clause", "show", "gdpr:art-17", "--subtree"])

    assert result.exit_code == 0
    assert "the personal data are no longer necessary" in result.output
    assert "gdpr:art-17:para-1:pt-a" in result.output
    assert "gdpr:art-17:para-3" in result.output


def test_a_clause_with_children_says_what_it_contains(loaded: None) -> None:
    """A lead-in ending 'one of the following applies:' must not stop there."""
    result = runner.invoke(app, ["clause", "show", "gdpr:art-17:para-1"])

    assert result.exit_code == 0
    assert "Contains 6: (a), (b), (c), (d), (e), (f)" in result.output
    assert "--subtree" in result.output


def test_a_link_is_shown_on_the_clause_that_states_it(loaded: None) -> None:
    point = runner.invoke(app, ["clause", "show", "gdpr:art-17:para-1:pt-b"])
    article = runner.invoke(app, ["clause", "show", "gdpr:art-17"])

    assert "point (a) of Article 6(1)" in point.output
    assert "Refers to:" not in article.output


def test_a_point_shows_its_breadcrumb(loaded: None) -> None:
    result = runner.invoke(app, ["clause", "show", "gdpr:art-17:para-1:pt-a"])

    assert result.exit_code == 0
    assert "Right to erasure" in result.output  # the breadcrumb names the article


def test_a_recital_is_marked_non_normative(loaded: None) -> None:
    result = runner.invoke(app, ["clause", "show", "gdpr-recitals:rec-65"])

    assert result.exit_code == 0
    assert "non-normative" in result.output


def test_an_unknown_key_fails_with_a_clear_message(loaded: None) -> None:
    result = runner.invoke(app, ["clause", "show", "gdpr:art-500"])

    assert result.exit_code == 1
    assert "gdpr:art-500" in result.output
