"""The UAE PDPL pack in this repository, loaded the way an instance loads it.

The text was taken from the official portal's web pages and checked against the
PDFs on the same pages. The web pages differ from the PDFs in places, some of
which change the meaning, so the tests below hold the pack to the PDF wording
where it matters most.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dpolens.engine.documents.models import DocumentNode, NodeText
from dpolens.engine.documents.read import get_clause
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration

UAE_PDPL_PACK = Path(__file__).parents[2] / "packs" / "uae-pdpl"


@pytest.fixture
def loaded(session: Session) -> Session:
    load_pack(session, UAE_PDPL_PACK)
    session.commit()
    return session


def test_loads_every_article_in_both_languages(loaded: Session) -> None:
    articles = loaded.scalar(
        select(func.count()).select_from(DocumentNode).where(DocumentNode.node_type == "article")
    )
    clauses = loaded.scalar(select(func.count()).select_from(DocumentNode))
    texts = dict(
        loaded.execute(select(NodeText.lang, func.count()).group_by(NodeText.lang)).tuples().all()
    )

    assert articles == 31
    assert texts == {"ar": clauses, "en": clauses}


def test_the_arabic_prevails(loaded: Session) -> None:
    clause = get_clause(loaded, "uae-pdpl:art-4", lang="en").clause

    assert clause.is_authoritative is False
    assert clause.authoritative_language == "ar"


def test_article_23_is_about_the_absence_of_adequate_protection(loaded: Session) -> None:
    """The web page gives article 23 the title of article 22; the PDF does not."""
    arabic = get_clause(loaded, "uae-pdpl:art-23", lang="ar").clause

    assert "في حال عدم وجود مستوى حماية ملائم" in (arabic.heading or "")


def test_consent_must_be_unambiguous(loaded: Session) -> None:
    """The web page has مهمة, unimportant, where the PDF has مبهمة, ambiguous."""
    point = get_clause(loaded, "uae-pdpl:art-6:para-1:pt-b", lang="ar").clause

    assert "وغير مبهمة" in point.text
    assert "وغير مهمة" not in point.text


def test_the_english_follows_the_arabic_numbering(loaded: Session) -> None:
    """The English web page numbers the first point of article 2(1) as 2."""
    point = get_clause(loaded, "uae-pdpl:art-2:para-1:pt-a", lang="en").clause

    assert point.label == "a."
    assert point.text.startswith("Each Data Subject residing in the State")


def test_articles_keep_the_laws_order(loaded: Session) -> None:
    order = dict(
        loaded.execute(
            select(DocumentNode.canonical_key, DocumentNode.order_index).where(
                DocumentNode.canonical_key.in_(("uae-pdpl:art-9", "uae-pdpl:art-10"))
            )
        )
        .tuples()
        .all()
    )

    assert order["uae-pdpl:art-9"] < order["uae-pdpl:art-10"]


def test_each_definition_is_a_clause_keyed_by_the_term_it_defines(loaded: Session) -> None:
    """Article 1 numbers none of its definitions, so each is keyed by its term as the official
    English prints it, and the Arabic sits under the same keys, in the same order."""
    rows = loaded.execute(
        select(
            DocumentNode.canonical_key, DocumentNode.node_type, NodeText.lang, NodeText.body_text
        )
        .join(NodeText, NodeText.node_id == DocumentNode.id)
        .where(DocumentNode.canonical_key.like("uae-pdpl:art-1:%"))
        .order_by(DocumentNode.order_index)
    ).all()
    english = [(row.canonical_key, row.body_text) for row in rows if row.lang == "en"]
    arabic = [row.canonical_key for row in rows if row.lang == "ar"]

    assert len(english) == 20
    assert {row.node_type for row in rows} == {"definition"}
    for key, words in english:
        term = words.split(":", 1)[0]
        assert key == "uae-pdpl:art-1:def-" + term.lower().replace(" ", "-")
    assert arabic == [key for key, _ in english]
    assert get_clause(loaded, "uae-pdpl:art-1:def-consent", lang="ar").clause.text.startswith(
        "الموافقة:"
    )
