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
POLICIES = Path(__file__).parents[1] / "fixtures" / "policies"
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


def test_a_policy_goes_from_a_file_to_a_citation(
    instance: None, clean_tables: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DPOLENS_ORIGINALS_DIR", str(tmp_path))
    first = str(POLICIES / "retention-v1.md")
    uploaded = runner.invoke(
        app, ["policy", "upload", first, "--slug", "retention", "--effective-date", "2026-01-01"]
    )
    assert uploaded.exit_code == 0, uploaded.output
    assert "Nothing to settle. Publish with: dpolens policy publish retention" in said(uploaded)
    published = runner.invoke(app, ["policy", "publish", "retention"])
    assert "Published version 1 of Retention policy, in force from 2026-01-01" in said(published)

    second = str(POLICIES / "retention-v2.md")
    revised = runner.invoke(
        app, ["policy", "revise", "retention", second, "--effective-date", "2026-06-01"]
    )
    assert revised.exit_code == 0, revised.output
    assert "Against version 1: 1 new, 1 reworded, 2 renumbered, 3 the same, 0 removed." in said(
        revised
    )
    assert "was 4.2" in revised.output

    refused = runner.invoke(app, ["policy", "publish", "retention"])
    assert refused.exit_code == 1
    assert "flags to settle before it can be published" in said(refused)
    accepted = runner.invoke(app, ["policy", "accept", "retention", "--all"])
    assert "Every flag is settled" in said(accepted)
    assert runner.invoke(app, ["policy", "publish", "retention"]).exit_code == 0

    cited = runner.invoke(app, ["clause", "show", "retention:4.2", "--as-of", "2026-01-01"])
    assert "Staff records" in cited.output
    assert (
        "In version 2, in force since 2026-06-01, this rule is retention:4.3, word for word."
        in (said(cited))
    )
    listed = runner.invoke(app, ["policy", "list"])
    assert "version 2" in listed.output


def test_a_match_can_be_said_to_be_a_different_rule(
    instance: None, clean_tables: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DPOLENS_ORIGINALS_DIR", str(tmp_path))
    first, second = str(POLICIES / "retention-v1.md"), str(POLICIES / "retention-v2.md")
    runner.invoke(
        app, ["policy", "upload", first, "--slug", "retention", "--effective-date", "2026-01-01"]
    )
    runner.invoke(app, ["policy", "publish", "retention"])
    runner.invoke(app, ["policy", "revise", "retention", second, "--effective-date", "2026-06-01"])

    rejected = runner.invoke(app, ["policy", "reject-match", "retention", "4.3"])

    assert rejected.exit_code == 0, rejected.output
    assert "4.3 is new in the draft, and version 1's 4.2 is removed." in said(rejected)
    shown = runner.invoke(app, ["policy", "draft", "retention"])
    assert "said to be a different rule by the command line" in said(shown)
    assert "2 new, 1 reworded, 1 renumbered, 3 the same, 1 removed." in said(shown)


def test_how_a_clause_was_read_is_fixed_from_the_shell(
    instance: None, clean_tables: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DPOLENS_ORIGINALS_DIR", str(tmp_path))
    runner.invoke(app, ["policy", "upload", str(POLICIES / "acceptable-use.md"), "--slug", "aup"])

    moved = runner.invoke(app, ["policy", "fix", "aup", "personal-use", "move-under"])
    split = runner.invoke(app, ["policy", "fix", "aup", "3.1", "split", "--before", "3.2 The"])
    refused = runner.invoke(app, ["policy", "fix", "aup", "1", "move-under"])
    nowhere = runner.invoke(app, ["policy", "fix", "aup", "2.1", "split", "--before", "never"])

    assert moved.exit_code == 0, moved.output
    assert "Moved personal-use under the clause before it. Its key is 2:personal-use." in said(
        moved
    )
    assert "Split 3.1. Still open: 2." in said(split)
    assert refused.exit_code == 1
    assert "no clause before it to move it under" in said(refused)
    assert nowhere.exit_code == 2
    assert "No sentence or paragraph of 2.1 starts with 'never'." in said(nowhere)
    shown = said(runner.invoke(app, ["policy", "draft", "aup"]))
    assert "(moved under the clause before by the command line)" in shown
    assert "3.2 The records are kept for 90 days. you" in shown


def test_a_policy_s_versions_are_listed_and_compared_from_the_shell(
    instance: None, clean_tables: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DPOLENS_ORIGINALS_DIR", str(tmp_path))
    first, second = str(POLICIES / "retention-v1.md"), str(POLICIES / "retention-v2.md")
    runner.invoke(
        app, ["policy", "upload", first, "--slug", "retention", "--effective-date", "2026-01-01"]
    )
    runner.invoke(app, ["policy", "publish", "retention"])
    runner.invoke(app, ["policy", "revise", "retention", second, "--effective-date", "2026-06-01"])
    runner.invoke(app, ["policy", "accept", "retention", "--all"])
    runner.invoke(app, ["policy", "publish", "retention"])

    listed = runner.invoke(app, ["policy", "versions", "retention"])
    compared = runner.invoke(app, ["policy", "compare", "retention", "1", "2"])
    itself = runner.invoke(app, ["policy", "compare", "retention", "2", "2"])

    assert listed.exit_code == 0, listed.output
    assert "2 in force from 2026-06-01" in said(listed)
    assert "1 replaced 2026-01-01 to 2026-05-31" in said(listed)
    assert compared.exit_code == 0, compared.output
    assert (
        "Version 1 to version 2: 1 new, 1 reworded, 2 renumbered, 3 the same, 0 removed."
        in said(compared)
    )
    assert "4.3 was 4.2" in said(compared)
    assert itself.exit_code == 1
    assert "Version 2 is the same version. Choose two different ones." in said(itself)


def test_a_policy_without_a_draft_says_so(instance: None, clean_tables: None) -> None:
    result = runner.invoke(app, ["policy", "publish", "nothing-here"])

    assert result.exit_code == 1
    assert "There is no policy called nothing-here." in said(result)
