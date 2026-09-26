"""Rescoring the head of a candidate list.

The ordering logic is tested with a stub scorer, so these run without
downloading a cross-encoder. Whether reranking actually helps is measured by the
evals, not asserted here.
"""

from __future__ import annotations

from dpolens.engine.search.fuse import Fused
from dpolens.engine.search.rerank import rerank


class StubReranker:
    """Scores a pair by how many words the passage shares with the query."""

    def scores(self, query: str, passages: list[str]) -> list[float]:
        wanted = set(query.lower().split())
        return [len(wanted & set(passage.lower().split())) for passage in passages]


def candidates(*keys: str) -> list[Fused]:
    return [
        Fused(key=key, lang="en", score=1.0 / position, ranks={"meaning": position})
        for position, key in enumerate(keys, start=1)
    ]


def test_the_head_is_reordered_by_the_cross_encoder() -> None:
    texts = {
        "a": "nothing relevant here",
        "b": "erasure of personal data without undue delay",
        "c": "something else entirely",
    }

    reordered = rerank(
        StubReranker(),  # type: ignore[arg-type]
        "erasure of personal data",
        candidates("a", "b", "c"),
        texts,
    )

    assert reordered[0].key == "b"


def test_the_tail_keeps_its_fused_order() -> None:
    """Only the head is worth the cost, so the rest is left alone."""
    texts = {key: "" for key in ("a", "b", "c", "d")}
    texts["d"] = "erasure personal data"

    reordered = rerank(
        StubReranker(),  # type: ignore[arg-type]
        "erasure personal data",
        candidates("a", "b", "c", "d"),
        texts,
        depth=2,
    )

    assert [item.key for item in reordered[2:]] == ["c", "d"], "d was never rescored"


def test_where_each_retriever_found_a_clause_survives_reranking() -> None:
    """A result still has to be able to say how it was found."""
    reordered = rerank(
        StubReranker(),  # type: ignore[arg-type]
        "data",
        candidates("a", "b"),
        {"a": "data", "b": "other"},
    )

    assert reordered[0].ranks == {"meaning": 1}


def test_an_empty_list_is_returned_unchanged() -> None:
    assert rerank(StubReranker(), "anything", [], {}) == []  # type: ignore[arg-type]


def test_a_clause_with_no_stored_text_is_scored_not_dropped() -> None:
    """A missing text is a bug elsewhere; losing the candidate would hide it."""
    reordered = rerank(StubReranker(), "data", candidates("a", "b"), {"a": "data"})  # type: ignore[arg-type]

    assert {item.key for item in reordered} == {"a", "b"}
