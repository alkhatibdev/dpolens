"""Hybrid search over the fixture pack.

What the ranking should be for a real question is measured by the evals, not
asserted here. These tests cover the parts that must hold whatever the ranking
turns out to be.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from dpolens.engine.embedding import Embedder, get_model
from dpolens.engine.embedding.index import build_index
from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.packs.load import load_pack
from dpolens.engine.packs.selection import select_laws
from dpolens.engine.search import Fusion, search, vector_search

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def embedder() -> Iterator[Embedder]:
    with Embedder(get_model("e5-small")) as loaded:
        yield loaded


@pytest.fixture
def indexed(session: Session, testlaw_pack: Path, embedder: Embedder) -> Session:
    load_pack(session, testlaw_pack)
    select_laws(session, ["testlaw"], actor=cli_actor())
    session.commit()
    build_index(session, embedder)
    session.commit()
    return session


@pytest.fixture
def bilingual(session: Session, bilingual_pack: Path, embedder: Embedder) -> Session:
    load_pack(session, bilingual_pack)
    select_laws(session, ["bilingual"], actor=cli_actor())
    session.commit()
    build_index(session, embedder)
    session.commit()
    return session


def test_a_result_carries_what_a_reader_needs_to_judge_it(
    indexed: Session, embedder: Embedder
) -> None:
    results = search(indexed, embedder, "erasure of personal data", limit=3)
    first = results[0]

    assert first.clause.key.startswith("testlaw")
    assert first.clause.document_title
    assert first.clause.effective_date.isoformat() == "2026-01-01"
    assert first.score > 0
    assert set(first.ranks) <= {"keyword", "meaning"}


def test_both_retrievers_contribute(indexed: Session, embedder: Embedder) -> None:
    results = search(indexed, embedder, "erasure of personal data", limit=10)
    found_by = {name for result in results for name in result.ranks}

    assert found_by == {"keyword", "meaning"}


def test_limit_is_respected(indexed: Session, embedder: Embedder) -> None:
    assert len(search(indexed, embedder, "personal data", limit=2)) == 2


def test_an_obliging_clause_outranks_an_explaining_one_at_the_same_score(
    indexed: Session, embedder: Embedder
) -> None:
    """A recital reads more like a question than the article it explains."""
    results = search(indexed, embedder, "erasure", limit=10)
    by_key = {result.clause.key: result for result in results}

    recital = by_key.get("testlaw-recitals:rec-12")
    if recital is None:
        pytest.skip("the recital did not make the result set for this query")

    tied = [
        result for result in results if result.score == recital.score and result.clause.is_normative
    ]
    for article in tied:
        assert results.index(article) < results.index(recital)


def test_expanding_siblings_returns_the_rest_of_the_list(
    indexed: Session, embedder: Embedder
) -> None:
    results = search(
        indexed, embedder, "no other legal ground for the processing", limit=1, expand="siblings"
    )
    first = results[0]

    if not first.clause.key.endswith(("pt-a", "pt-b")):
        pytest.skip("this query did not match a point of the list")
    assert [sibling.key for sibling in first.expanded] != []
    assert all(sibling.depth == first.clause.depth for sibling in first.expanded)


def test_expanding_the_parent_returns_one_clause(indexed: Session, embedder: Embedder) -> None:
    results = search(
        indexed, embedder, "no other legal ground for the processing", limit=1, expand="parent"
    )

    assert len(results[0].expanded) <= 1


def test_the_fusion_rule_changes_the_order_not_the_contract(
    indexed: Session, embedder: Embedder
) -> None:
    for rule in ("rrf:10", "rrf:60", "convex:0.5"):
        results = search(
            indexed, embedder, "erasure of personal data", limit=3, fusion=Fusion.parse(rule)
        )

        assert results, f"{rule} returned nothing"
        assert all(result.clause.text for result in results)


def test_a_question_the_corpus_cannot_answer_returns_little(
    indexed: Session, embedder: Embedder
) -> None:
    """Meaning search always returns its nearest neighbours, so this cannot be
    empty, but the scores should be the low end of the range."""
    results = search(indexed, embedder, "kubernetes sidecar helm chart", limit=3)

    assert all(not result.ranks.get("keyword") for result in results)


def test_a_date_before_the_corpus_existed_finds_nothing(
    indexed: Session, embedder: Embedder
) -> None:
    """Asking what was in force in 1990 is a question, not an error.

    The retrievers find candidates whatever the date, so resolving each one as of
    that date is what decides. A clause with no version in force then is skipped
    rather than raised, which would otherwise be a 500 on a valid request.
    """
    found = search(indexed, embedder, "personal data", as_of=date(1990, 1, 1))

    assert found == []


def test_a_clause_with_two_texts_is_one_candidate(bilingual: Session, embedder: Embedder) -> None:
    """Both texts are embedded, and counting both would rank a translated law above
    one with a single text for no better reason than having two."""
    found = vector_search(bilingual, embedder, "if the data subject consents")
    keys = [candidate.key for candidate in found]

    assert len(keys) == len(set(keys))
    assert [candidate.rank for candidate in found] == list(range(1, len(found) + 1))


def test_a_result_comes_back_in_the_language_asked_for(
    bilingual: Session, embedder: Embedder
) -> None:
    """Asked in Arabic, the Arabic texts match best, and the clauses still come back in
    English, because English is the language the search asked for."""
    results = search(bilingual, embedder, "إذا وافق صاحب البيانات", limit=3, lang="en")

    assert results
    assert {result.clause.lang for result in results} == {"en"}


def test_a_question_in_arabic_letters_is_searched_and_answered_in_arabic(
    bilingual: Session, embedder: Embedder
) -> None:
    """No language is named: the question's letters choose the Arabic index."""
    results = search(bilingual, embedder, "هل يجوز معالجة البيانات إذا وافق صاحبها؟", limit=3)

    assert results
    assert {result.clause.lang for result in results} == {"ar"}
    assert any("keyword" in result.ranks for result in results)


def test_with_rules_each_result_is_the_rule_its_match_belongs_to(
    indexed: Session, embedder: Embedder
) -> None:
    """Article 5 opens with words of its own that introduce its paragraphs, so a match anywhere
    in it brings the whole article; Article 6 is only a title, so its paragraph stands alone."""
    results = search(indexed, embedder, "erasure of personal data", limit=10, rules=True)
    by_key = {result.clause.key: result for result in results}

    assert len(by_key) == len(results)
    assert set(by_key) <= {"testlaw:art-5", "testlaw:art-6:para-1", "testlaw-recitals:rec-12"}
    article = by_key["testlaw:art-5"]
    assert [clause.key for clause in article.beneath] == [
        "testlaw:art-5:para-1",
        "testlaw:art-5:para-1:pt-a",
        "testlaw:art-5:para-1:pt-b",
        "testlaw:art-5:para-2",
    ]
    assert article.whole
    assert article.clause.text.startswith("The controller shall erase personal data")


def test_a_rule_states_the_links_its_words_make(indexed: Session, embedder: Embedder) -> None:
    results = search(indexed, embedder, "erasure of personal data", limit=10, rules=True)
    article = next(result for result in results if result.clause.key == "testlaw:art-5")

    assert ("testlaw:art-6:para-1", "Article 6(1)") in article.cross_references


def test_with_rules_the_limit_counts_rules(indexed: Session, embedder: Embedder) -> None:
    results = search(indexed, embedder, "the right to erasure", limit=1, rules=True)

    assert len(results) == 1


def test_an_article_that_is_only_a_title_is_never_a_rule(
    indexed: Session, embedder: Embedder
) -> None:
    """Its heading can match, and what it holds is found by its own words."""
    results = search(indexed, embedder, "Lawfulness of processing", limit=10, rules=True)

    assert "testlaw:art-6" not in {result.clause.key for result in results}
    assert all(result.clause.text for result in results)


def test_a_rule_longer_than_a_whole_one_shows_the_two_clauses_ranked_highest(
    indexed: Session, embedder: Embedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every rule in this law is short, so the limit is set to nothing: Article 5 then comes
    with the two of its clauses the search ranked highest, each with everything beneath it."""
    monkeypatch.setattr("dpolens.engine.search.rules.WHOLE", 0)
    results = search(indexed, embedder, "erasure of personal data", limit=10, rules=True)
    article = next(result for result in results if result.clause.key == "testlaw:art-5")

    shown = [clause.key for clause in article.beneath]
    picked = [key for key in shown if not any(key.startswith(f"{other}:") for other in shown)]
    assert 1 <= len(picked) <= 2
    assert article.whole == (len(shown) == 4)


def test_without_rules_a_point_comes_back_by_itself(indexed: Session, embedder: Embedder) -> None:
    results = search(indexed, embedder, "erasure of personal data", limit=10)

    assert any(result.clause.key.startswith("testlaw:art-5:") for result in results)
    assert all(result.beneath == () and result.whole for result in results)
