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
from dpolens.engine.packs.load import load_pack
from dpolens.engine.search import Fusion, search, vector_search

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def embedder() -> Iterator[Embedder]:
    with Embedder(get_model("e5-small")) as loaded:
        yield loaded


@pytest.fixture
def indexed(session: Session, testlaw_pack: Path, embedder: Embedder) -> Session:
    load_pack(session, testlaw_pack)
    session.commit()
    build_index(session, embedder)
    session.commit()
    return session


@pytest.fixture
def bilingual(session: Session, bilingual_pack: Path, embedder: Embedder) -> Session:
    load_pack(session, bilingual_pack)
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
