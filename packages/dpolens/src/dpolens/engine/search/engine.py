"""Hybrid search: the one function every surface will call.

Keyword and meaning retrieval run over the same clauses, their lists are fused,
and each result comes back with what a reader needs to judge it: where it sits,
whether it obliges anyone, and which version it came from.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from dpolens.engine.documents.read import (
    ClauseDetail,
    ClauseNotFound,
    ClauseView,
    get_clause,
    get_subtree,
)
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.packs.selection import Scope, scope_for
from dpolens.engine.search.fuse import DEFAULT_FUSION, Fused, Fusion, fuse
from dpolens.engine.search.keyword import KeywordIndex, keyword_search
from dpolens.engine.search.language import language_of
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
    in_selected_laws: bool = True
    """False for a law the organisation has not selected, which a search reaches
    only when it names that law."""


def search(
    session: Session,
    embedder: Embedder,
    query: str,
    limit: int = 10,
    lang: str | None = None,
    expand: Expand = "none",
    fusion: Fusion = DEFAULT_FUSION,
    as_of: date | None = None,
    normative_only: bool = False,
    keyword_indexes: Mapping[str, KeywordIndex] | None = None,
    scope: Scope | None = None,
) -> list[SearchResult]:
    """The clauses that answer a question, best first.

    Without `lang`, the question's own letters say which language it is in.
    `keyword_indexes` swaps a language's keyword index for another, for the evals.
    Without `scope`, the search covers the organisation's selected laws.
    """
    lang = lang or language_of(query)
    scope = scope or scope_for(session)
    # Nothing is filtered when no loaded law is left out, so the default on an
    # instance where nobody has chosen runs exactly the search it always did.
    packs = list(scope.laws) if scope.narrowed else None
    lists = {
        "keyword": keyword_search(
            session,
            query,
            lang=lang,
            limit=CANDIDATE_DEPTH,
            normative_only=normative_only,
            indexes=keyword_indexes,
            packs=packs,
        ),
        "meaning": vector_search(
            session,
            embedder,
            query,
            limit=CANDIDATE_DEPTH,
            normative_only=normative_only,
            packs=packs,
        ),
    }
    fused = fuse(lists, fusion)

    # A candidate the retrievers found may have no version in force on the date
    # being asked about, which is not an error: it is a clause that did not say
    # this then, so it is not an answer now. Candidates are read in order until
    # enough are answers, so one that is passed over leaves no slot empty.
    #
    # Each clause is read in the language asked for, whichever of its texts
    # matched, and in the language that prevails where it has no text in that one.
    resolved: list[tuple[Fused, ClauseDetail]] = []
    for candidate in fused:
        if len(resolved) == limit + TIE_MARGIN:
            break
        try:
            detail = get_clause(session, candidate.key, lang=lang, as_of=as_of)
        except ClauseNotFound:
            continue
        # An archived policy no longer applies. Its clauses still read by key, so an old
        # citation can be checked, but nothing searches them.
        if detail.clause.archived:
            continue
        resolved.append((candidate, detail))

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
            expanded=_expanded(session, detail, expand, lang, as_of),
            in_selected_laws=scope.is_selected(detail.clause.pack_slug),
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
