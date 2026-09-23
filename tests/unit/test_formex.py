"""Converting Formex XML into clauses.

The fixture covers every shape the GDPR source actually contains: numbered
paragraphs, a second subparagraph, alphabetic and dash lists, a nested list, a
footnote, quotation marks, and an article whose points hang directly off it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dpolens.engine.packs.format import Clause
from dpolens.engine.packs.formex import FormexError, parse_articles, parse_recitals

FIXTURES = Path(__file__).parents[1] / "fixtures" / "formex"


@pytest.fixture(scope="module")
def articles() -> list[Clause]:
    return parse_articles(FIXTURES / "act.xml", "testlaw")


def test_reads_every_article(articles: list[Clause]) -> None:
    assert [article.key for article in articles] == ["testlaw:art-5", "testlaw:art-6"]


def test_keeps_quotation_marks_from_the_source(articles: list[Clause]) -> None:
    assert articles[0].heading == "Right to erasure (‘right to be forgotten’)"


def test_paragraphs_and_points(articles: list[Clause]) -> None:
    paragraph = articles[0].children[0]

    assert paragraph.key == "testlaw:art-5:para-1"
    assert paragraph.label == "1."
    assert paragraph.body_text.startswith("The controller shall erase")
    assert [child.key for child in paragraph.children][:2] == [
        "testlaw:art-5:para-1:pt-a",
        "testlaw:art-5:para-1:pt-b",
    ]


def test_a_second_subparagraph_becomes_its_own_clause(articles: list[Clause]) -> None:
    """Dropping it silently would lose a provision, which happened before this test."""
    paragraph = articles[0].children[0]
    subparagraph = paragraph.children[-1]

    assert subparagraph.key == "testlaw:art-5:para-1:sub-2"
    assert subparagraph.clause_type == "subparagraph"
    assert subparagraph.body_text.startswith("Point (a) of the first subparagraph")


def test_dash_lists_are_numbered_by_position(articles: list[Clause]) -> None:
    points = articles[0].children[1].children

    assert [point.key for point in points] == [
        "testlaw:art-5:para-2:pt-1",
        "testlaw:art-5:para-2:pt-2",
    ]
    assert points[0].label is None
    assert points[0].body_text == "their parliament;"


def test_an_article_without_paragraphs_keeps_its_points(articles: list[Clause]) -> None:
    """Article 4 of GDPR is shaped like this, and its definitions are cited constantly."""
    definitions = articles[1]

    assert definitions.body_text == "For the purposes of this Regulation:"
    assert [child.key for child in definitions.children] == [
        "testlaw:art-6:pt-1",
        "testlaw:art-6:pt-2",
    ]


def test_footnotes_are_left_out_of_clause_text(articles: list[Clause]) -> None:
    consent = articles[1].children[0]

    assert consent.body_text == "‘consent’ means any freely given indication of wishes;"


def test_nested_lists_become_child_clauses(articles: list[Clause]) -> None:
    nested = articles[1].children[1].children

    assert [child.key for child in nested] == ["testlaw:art-6:pt-2:pt-a"]


def test_reads_recitals_as_non_normative() -> None:
    recitals = parse_recitals(FIXTURES / "recitals.xml", "testlaw-recitals")

    assert [recital.key for recital in recitals] == [
        "testlaw-recitals:rec-1",
        "testlaw-recitals:rec-2",
    ]
    assert all(recital.normative is False for recital in recitals)
    assert recitals[0].body_text.startswith("The protection of natural persons")


def test_a_consolidated_text_has_no_recitals() -> None:
    with pytest.raises(FormexError, match="no CONSID elements"):
        parse_recitals(FIXTURES / "act.xml", "testlaw-recitals")


def test_a_preamble_file_has_no_articles() -> None:
    with pytest.raises(FormexError, match="no ARTICLE elements"):
        parse_articles(FIXTURES / "recitals.xml", "testlaw")
