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
    first_paragraph,
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
    returned_with: str | None = None
    """The result this one follows, when it is the first paragraph of that result's article."""


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
    Without `scope`, the search covers the organisation's selected laws, and is
    refused until somebody has chosen them.

    A result from a later paragraph of an article is followed by the article's first
    paragraph, which states the rule the later one qualifies.
    """
    lang = lang or language_of(query)
    scope = scope or scope_for(session)
    # Nothing is filtered when no loaded law is left out, so an instance with one
    # law, or with every law selected, runs exactly the search it always did.
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
            as_of=as_of,
        ),
        "meaning": vector_search(
            session,
            embedder,
            query,
            limit=CANDIDATE_DEPTH,
            normative_only=normative_only,
            packs=packs,
            as_of=as_of,
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
        detail = _answer(session, candidate.key, lang, as_of)
        if detail is not None:
            resolved.append((candidate, detail))

    # A clause that obliges someone outranks one that only explains, where the
    # retrievers cannot separate them. A recital reads more like a question than
    # the article it explains, so without this the explanation wins the slot.
    resolved.sort(key=lambda pair: (-pair[0].score, not pair[1].clause.is_normative))

    return [
        SearchResult(
            clause=detail.clause,
            score=score,
            ranks=ranks,
            breadcrumb=detail.breadcrumb,
            cross_references=detail.cross_references,
            expanded=_expanded(session, detail, expand, lang, as_of),
            returned_with=returned_with,
        )
        for detail, score, ranks, returned_with in _placed(
            session, fused, resolved, limit, lang, as_of, normative_only
        )
    ]


def _answer(session: Session, key: str, lang: str, as_of: date | None) -> ClauseDetail | None:
    """The clause as a result, or None when it is no answer on the day asked about."""
    try:
        detail = get_clause(session, key, lang=lang, as_of=as_of)
    except ClauseNotFound:
        return None
    # An archived policy no longer applies, and nor do words a law has ended. Both still
    # read by key, so an old citation can be checked, but nothing searches them.
    if detail.clause.archived or _ended(detail.clause, as_of or date.today()):
        return None
    return detail


def _placed(
    session: Session,
    fused: list[Fused],
    resolved: list[tuple[Fused, ClauseDetail]],
    limit: int,
    lang: str,
    as_of: date | None,
    normative_only: bool,
) -> list[tuple[ClauseDetail, float, dict[str, int], str | None]]:
    """The results in the order they are read, each with its score, ranks and what it follows.

    Asked for a copy of what is held about somebody, search ranks Article 15(4), on the copy,
    above 15(1), which grants it, because 15(4) uses the question's words. So a result from a
    later paragraph is followed by its article's first paragraph, at that result's score, so
    the list still reads best first. One found lower comes up rather than appearing twice, and
    the list still ends at `limit`.
    """
    found = {candidate.key: candidate for candidate in fused}
    details = {candidate.key: detail for candidate, detail in resolved}
    placed: list[tuple[ClauseDetail, float, dict[str, int], str | None]] = []
    shown: set[str] = set()
    for candidate, detail in resolved:
        if len(placed) == limit:
            break
        if candidate.key in shown:
            continue
        placed.append((detail, candidate.score, candidate.ranks, None))
        shown.add(candidate.key)

        first = first_paragraph(session, detail, as_of)
        if first is None or first in shown or len(placed) == limit:
            continue
        lead = details.get(first) or _answer(session, first, lang, as_of)
        if lead is None or (normative_only and not lead.clause.is_normative):
            continue
        ranks = found[first].ranks if first in found else {}
        placed.append((lead, candidate.score, ranks, candidate.key))
        shown.add(first)
    return placed


def _ended(clause: ClauseView, as_of: date) -> bool:
    return clause.in_force_until is not None and clause.in_force_until <= as_of


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
