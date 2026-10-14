"""The command line, against a real database.

This is the shape of step 1a: load the pack, print an article, read it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import click
import pytest
from typer.testing import CliRunner, Result

from dpolens.cli.main import app

pytestmark = pytest.mark.integration

GDPR_PACK = Path(__file__).parents[2] / "packs" / "gdpr"
runner = CliRunner()
BORDERS = str.maketrans(dict.fromkeys("│╭╮╰╯─", " "))


def said(result: Result) -> str:
    """The output as the words a person reads, on one line.

    On CI, Typer draws a usage error in a coloured box wrapped at the terminal's
    width, so a sentence can arrive split by colour codes, borders and line breaks.
    """
    return " ".join(click.unstyle(result.output).translate(BORDERS).split())


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


def test_a_pack_of_one_document_says_one_document(
    instance: None, clean_tables: None, bilingual_pack: Path
) -> None:
    result = runner.invoke(app, ["pack", "load", str(bilingual_pack)])

    assert result.exit_code == 0
    assert result.output.rstrip().endswith("across 1 document")


def test_a_translation_says_which_text_prevails(
    instance: None, clean_tables: None, bilingual_pack: Path
) -> None:
    assert runner.invoke(app, ["pack", "load", str(bilingual_pack)]).exit_code == 0

    result = runner.invoke(app, ["clause", "show", "bilingual:art-2", "--lang", "en"])

    assert result.exit_code == 0
    assert "Cases of Processing" in result.output
    assert "en translation, ar prevails" in result.output


def test_a_point_read_in_translation_shows_the_text_that_prevails(
    instance: None, clean_tables: None, bilingual_pack: Path
) -> None:
    assert runner.invoke(app, ["pack", "load", str(bilingual_pack)]).exit_code == 0

    result = runner.invoke(app, ["clause", "show", "bilingual:art-2:para-1:pt-a", "--lang", "en"])

    assert result.exit_code == 0
    assert "If the Data Subject consents." in result.output
    assert "The ar text, which prevails:" in result.output
    assert "إذا وافق صاحب البيانات." in result.output


def test_an_unknown_key_fails_with_a_clear_message(loaded: None) -> None:
    result = runner.invoke(app, ["clause", "show", "gdpr:art-500"])

    assert result.exit_code == 1
    assert "gdpr:art-500" in result.output


def test_an_eval_run_naming_a_modifier_nothing_reads_stops_before_it_starts() -> None:
    result = runner.invoke(
        app, ["evals", "run", "--pack", "uae-pdpl", "--config", "convex:0.5+normative+ligth"]
    )

    assert result.exit_code == 2
    assert "+ligth" in said(result)


def test_every_law_is_searched_until_one_is_chosen(loaded: None) -> None:
    listed = runner.invoke(app, ["laws", "list"])
    chosen = runner.invoke(app, ["laws", "select", "gdpr"])
    after = runner.invoke(app, ["laws", "list"])
    cleared = runner.invoke(app, ["laws", "clear"])

    assert listed.exit_code == 0
    assert "every search covers every loaded law" in listed.output
    assert chosen.exit_code == 0, chosen.output
    assert "Selected: gdpr" in chosen.output
    assert "every search covers every loaded law" not in after.output
    assert cleared.exit_code == 0
    assert "every search covers every loaded law" in cleared.output


def test_choosing_a_law_that_is_not_loaded_fails_naming_the_loaded_ones(loaded: None) -> None:
    result = runner.invoke(app, ["laws", "select", "uae-pdpl"])

    assert result.exit_code == 1
    assert "The loaded laws are: gdpr" in result.output


def test_only_a_held_out_set_is_written_and_before_anything_runs() -> None:
    result = runner.invoke(
        app,
        ["evals", "run", "--pack", "gdpr", "--set", "held_out", "--set", "tuning.ar", "--write"],
    )

    assert result.exit_code == 2
    assert "--write is for held-out sets, not 'tuning.ar'" in said(result)


def test_scoring_together_needs_two_sets() -> None:
    result = runner.invoke(
        app, ["evals", "run", "--pack", "gdpr", "--set", "held_out", "--together"]
    )

    assert result.exit_code == 2
    assert "at least two sets" in said(result)
