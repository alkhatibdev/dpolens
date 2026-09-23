"""Writing clauses out, and proving the source survived the round trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from dpolens.engine.packs.format import Clause, read_clause_file
from dpolens.engine.packs.formex import parse_articles, text_of
from dpolens.engine.packs.write import CoverageError, check_coverage, link_clauses, write_document

FIXTURES = Path(__file__).parents[1] / "fixtures" / "formex"


@pytest.fixture(scope="module")
def articles() -> list[Clause]:
    return parse_articles(FIXTURES / "act.xml", "testlaw")


def test_a_written_clause_reads_back_the_same(tmp_path: Path, articles: list[Clause]) -> None:
    write_document(tmp_path / "testlaw", articles, "testlaw")

    original = articles[0]
    reloaded = read_clause_file(tmp_path / "testlaw" / "art-5.md")

    assert reloaded.key == original.key
    assert reloaded.heading == original.heading
    assert [c.key for c in reloaded.walk()] == [c.key for c in original.walk()]
    assert [c.body_text for c in reloaded.walk()] == [c.body_text for c in original.walk()]
    assert [c.label for c in reloaded.walk()] == [c.label for c in original.walk()]


def test_files_are_named_after_the_last_key_segment(tmp_path: Path, articles: list[Clause]) -> None:
    write_document(tmp_path / "testlaw", articles, "testlaw")

    assert sorted(path.name for path in (tmp_path / "testlaw").glob("*.md")) == [
        "art-5.md",
        "art-6.md",
    ]


def test_a_link_belongs_to_the_clause_that_states_it(
    tmp_path: Path, articles: list[Clause]
) -> None:
    """The point that cites Article 5(2) is what refers to it, not the whole article."""
    write_document(tmp_path / "testlaw", articles, "testlaw")
    reloaded = read_clause_file(tmp_path / "testlaw" / "art-5.md")

    article = reloaded
    point = next(c for c in reloaded.walk() if c.key == "testlaw:art-5:para-1:pt-b")

    assert article.cross_references == ()
    assert [reference.key for reference in point.cross_references] == ["testlaw:art-5:para-2"]


def test_links_are_stored_only_when_the_target_exists(articles: list[Clause]) -> None:
    links, dangling = link_clauses(articles, "testlaw")

    stored = {reference.target_key for references in links.values() for reference in references}

    # Article 5(2) exists in the fixture, so the link is made. The reference to
    # Directive 95/46/EC names another law and is left alone.
    assert stored == {"testlaw:art-5:para-2"}
    assert dangling == []


def test_coverage_accepts_text_laid_out_differently(articles: list[Clause]) -> None:
    from xml.etree import ElementTree

    root = ElementTree.parse(FIXTURES / "act.xml").getroot()
    element = next(root.iter("ARTICLE"))

    check_coverage(text_of(element), articles[0])


def test_coverage_catches_a_dropped_clause(articles: list[Clause]) -> None:
    """The failure this check exists for: a provision missing from the pack."""
    from xml.etree import ElementTree

    root = ElementTree.parse(FIXTURES / "act.xml").getroot()
    element = next(root.iter("ARTICLE"))
    truncated = Clause(
        key=articles[0].key,
        clause_type=articles[0].clause_type,
        label=articles[0].label,
        heading=articles[0].heading,
        body_text=articles[0].body_text,
        lang=articles[0].lang,
        normative=True,
        children=articles[0].children[:1],
    )

    with pytest.raises(CoverageError, match="does not carry the source text"):
        check_coverage(text_of(element), truncated)
