"""Hybrid search: the one function every surface will call.

Keyword and meaning retrieval run over the same clauses, their lists are fused,
and each result comes back with what a reader needs to judge it: where it sits,
whether it obliges anyone, and which version it came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from dpolens.engine.documents.read import ClauseDetail, ClauseView, get_clause, get_subtree
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.search.fuse import RRF, Fusion, fuse
from dpolens.engine.search.keyword import keyword_search
from dpolens.engine.search.vector import vector_search

CANDIDATE_DEPTH = 100
"""How deep each retriever goes before fusion. Fusion cannot recover what
neither retriever returned, and the reranker later sees only the top of this."""

TIE_MARGIN = 5
"""How many extra candidates to resolve, so the normative rule can decide the
last slot rather than being applied after it has been given away."""

Expand = Literal["none", "siblings", "parent"]


@dataclass(frozen=True)
class SearchResult:
    """One clause, ready to be read or cited."""

    clause: ClauseView
    score: float
    ranks: dict[str, int]
    breadcrumb: tuple[ClauseView, ...]
    cross_references: tuple[tuple[str, str], ...]
    expanded: tuple[ClauseView, ...] = ()


def search(
    session: Session,
    embedder: Embedder,
    query: str,
    limit: int = 10,
    lang: str = "en",
    expand: Expand = "none",
    fusion: Fusion = RRF,
    as_of: date | None = None,
    normative_only: bool = False,
) -> list[SearchResult]:
    """The clauses that answer a question, best first."""
    lists = {
        "keyword": keyword_search(
            session, query, lang=lang, limit=CANDIDATE_DEPTH, normative_only=normative_only
        ),
        "meaning": vector_search(
            session, embedder, query, limit=CANDIDATE_DEPTH, normative_only=normative_only
        ),
    }
    fused = fuse(lists, fusion)[: limit + TIE_MARGIN]

    resolved = [
        (candidate, get_clause(session, candidate.key, lang=candidate.lang, as_of=as_of))
        for candidate in fused
    ]

    # A clause that obliges someone outranks one that only explains, where the
    # retrievers cannot separate them. A recital reads more like a question than
    # the article it explains, so without this the explanation wins the slot.
    resolved.sort(key=lambda pair: (-pair[0].score, not pair[1].clause.is_normative))

    return [
        SearchResult(
            clause=detail.clause,
            score=candidate.score,
            ranks=candidate.ranks,
            breadcrumb=detail.breadcrumb,
            cross_references=detail.cross_references,
            expanded=_expanded(session, detail, expand, candidate.lang, as_of),
        )
        for candidate, detail in resolved[:limit]
    ]


def _expanded(
    session: Session,
    detail: ClauseDetail,
    expand: Expand,
    lang: str,
    as_of: date | None,
) -> tuple[ClauseView, ...]:
    """Optionally bring back what sits around a match, in one call.

    A point of Article 17(1) rarely answers a question by itself, and an
    assistant asking for its siblings should not have to make six more calls.
    """
    if expand == "none":
        return ()

    parent = detail.breadcrumb[-1] if detail.breadcrumb else None
    if parent is None:
        return ()
    if expand == "parent":
        return (parent,)

    family = get_subtree(session, parent.key, lang=lang, as_of=as_of)
    return tuple(
        found
        for found in family
        if found.key != detail.clause.key and found.depth == detail.clause.depth
    )
