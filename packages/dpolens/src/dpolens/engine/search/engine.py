"""Hybrid search: the one function every surface will call.

Each law the search covers is ranked by itself, and so are the organisation's own policies:
keyword and meaning retrieval over that source's clauses, with a law's search questions as a
list of their own, fused into one ranking. The sources then take turns in the results, the one
whose best match is closest first. Each result comes back with what a reader needs to judge it:
where it sits, whether it obliges anyone, and which version it came from.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

import numpy as np
from sqlalchemy.orm import Session

from dpolens.engine.documents.read import (
    ClauseDetail,
    ClauseView,
    get_clauses,
    get_subtree,
    get_whole,
)
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.packs.selection import Scope, scope_for
from dpolens.engine.search.fuse import DEFAULT_FUSION, Fused, Fusion, fuse
from dpolens.engine.search.keyword import KeywordIndex, keyword_search, quoted
from dpolens.engine.search.language import language_of
from dpolens.engine.search.questions import nearest_questions, questions_on, with_questions
from dpolens.engine.search.rules import ended, rule_of, shown
from dpolens.engine.search.vector import vector_search

CANDIDATE_DEPTH = 100
"""How deep each retriever goes before fusion. Fusion cannot recover what
no retriever returned, and the reranker later sees only the top of this."""

TIE_MARGIN = 5
"""How many extra candidates to resolve, so the normative rule can decide the
last slot rather than being applied after it has been given away."""

READ_AHEAD = 20
"""How many candidates are read from the database at once. A search reads about fifteen
clauses for each source, more for whole rules, and reading them together is a handful of
queries where reading each alone is ten."""

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
    beneath: tuple[ClauseView, ...] = ()
    """In a search for whole rules, the clauses shown beneath the rule's own words, in reading
    order, each with its own key to cite it by."""
    whole: bool = True
    """False when a rule too long to show whole comes back as its own words and the clauses
    beneath them the search ranked highest."""


@dataclass(frozen=True)
class Ranked:
    """One source's clauses, best first, and how close its best match came."""

    law: str | None
    """The law's pack, or None for the organisation's own policies."""
    candidates: list[Fused]
    strength: float


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
    questions: bool | None = None,
    rules: bool = False,
) -> list[SearchResult]:
    """The clauses that answer a question, the best of each source in turn.

    Without `lang`, the question's own letters say which language it is in.
    `keyword_indexes` swaps a language's keyword index for another, for the evals.
    Without `scope`, the search covers the organisation's selected laws, and is
    refused until somebody has chosen them. Without `questions`, the search
    questions are used unless the organisation has turned them off. With `rules`,
    each result is the whole rule its best match belongs to (see `rules.py`), and
    `limit` counts rules.
    """
    lang = lang or language_of(query)
    scope = scope or scope_for(session)
    vector = embedder.encode_query(query)
    # The questions were written for the words in force today, so a search of another day,
    # which reads other words, goes without them.
    asking = (questions_on(session) if questions is None else questions) and as_of in (
        None,
        date.today(),
    )
    # A law's questions score on a higher scale than any clause's own words, since a question
    # resembles a question more than legal text. Ranked in one list, a source without them,
    # such as the organisation's policies or a law whose questions are not written yet, would
    # sink below one with them. Ranked apart, each keeps its share of the results.
    sources = [
        _ranked(
            session,
            embedder,
            query,
            vector,
            law,
            lang=lang,
            fusion=fusion,
            as_of=as_of,
            normative_only=normative_only,
            keyword_indexes=keyword_indexes,
            asking=asking and law is not None,
        )
        for law in [*scope.laws, None]
    ]

    # A candidate the retrievers found may have no version in force on the date
    # being asked about, which is not an error: it is a clause that did not say
    # this then, so it is not an answer now. Candidates are read in order until
    # enough are answers, so one that is passed over leaves no slot empty.
    #
    # Each clause is read in the language asked for, whichever of its texts
    # matched, and in the language that prevails where it has no text in that one.
    resolved = _in_turns(session, sources, limit + TIE_MARGIN, lang=lang, as_of=as_of, rules=rules)
    if rules:
        return [_whole_rule(session, answer, expand, lang, as_of) for answer in resolved[:limit]]
    return [
        SearchResult(
            clause=answer.detail.clause,
            score=answer.candidate.score,
            ranks=answer.candidate.ranks,
            breadcrumb=answer.detail.breadcrumb,
            cross_references=answer.detail.cross_references,
            expanded=_expanded(
                session, answer.detail.clause, answer.detail.breadcrumb, expand, lang, as_of
            ),
        )
        for answer in resolved[:limit]
    ]


def _ranked(
    session: Session,
    embedder: Embedder,
    query: str,
    vector: np.ndarray,
    law: str | None,
    *,
    lang: str,
    fusion: Fusion,
    as_of: date | None,
    normative_only: bool,
    keyword_indexes: Mapping[str, KeywordIndex] | None,
    asking: bool,
) -> Ranked:
    """One law's clauses, or the organisation's policies, ranked by themselves."""
    packs = [law] if law is not None else []
    keyword = keyword_search(
        session,
        query,
        lang=lang,
        limit=CANDIDATE_DEPTH,
        normative_only=normative_only,
        indexes=keyword_indexes,
        packs=packs,
        as_of=as_of,
        policies=law is None,
        with_questions=asking,
    )
    meaning = vector_search(
        session,
        embedder,
        query,
        limit=CANDIDATE_DEPTH,
        normative_only=normative_only,
        packs=packs,
        as_of=as_of,
        vector=vector,
        policies=law is None,
    )
    asked = (
        nearest_questions(
            session,
            embedder,
            vector,
            law,
            limit=CANDIDATE_DEPTH,
            normative_only=normative_only,
        )
        if asking and law is not None
        else []
    )
    fused = fuse({"keyword": keyword, "meaning": with_questions(meaning, asked)}, fusion)
    # Keyword search counts for less than meaning, which suits a question in everyday words. A
    # question that repeats a clause's own words is asking for that clause, wherever the sum put it.
    quote = quoted(session, query, lang, [candidate.key for candidate in keyword[:10]], as_of)
    if quote is not None:
        fused = sorted(fused, key=lambda item: item.key != quote)
    places = {
        "keyword": {candidate.key: candidate.rank for candidate in keyword},
        "meaning": {candidate.key: candidate.rank for candidate in meaning},
        "questions": {candidate.key: candidate.rank for candidate in asked},
    }
    return Ranked(
        law=law,
        candidates=[
            replace(
                item,
                ranks={
                    name: ranked[item.key] for name, ranked in places.items() if item.key in ranked
                },
            )
            for item in fused
        ],
        strength=max([candidate.score for candidate in [*meaning[:1], *asked[:1]]], default=0.0),
    )


@dataclass
class _Answer:
    """A candidate that answers on the day asked about, and what comes back for it."""

    candidate: Fused
    detail: ClauseDetail
    rule: str
    """The key of what comes back: the clause itself, or the rule it belongs to."""
    reached: list[str] = field(default_factory=list)
    """The rule's clauses the search came to, its best first."""


def _in_turns(
    session: Session,
    sources: Sequence[Ranked],
    wanted: int,
    *,
    lang: str,
    as_of: date | None,
    rules: bool = False,
) -> list[_Answer]:
    """The sources' answers taking turns, the source whose best match is closest first.

    Within a source, a clause that obliges someone outranks one that only explains where their
    scores cannot separate them. A recital reads more like a question than the article it
    explains, so without this the explanation would win the slot. Nothing else in a source's
    order moves.
    """
    order = sorted(
        (source for source in sources if source.candidates),
        key=lambda source: (-source.strength, source.law is None, source.law or ""),
    )
    grouped = _by_rule if rules else _by_clause
    queues = {
        id(source): grouped(_answers(session, source.candidates, lang, as_of)) for source in order
    }
    taken: dict[int, list[_Answer]] = {id(source): [] for source in order}
    turns: list[int] = []
    waiting = list(order)
    while waiting and len(turns) < wanted:
        for source in list(waiting):
            if len(turns) == wanted:
                break
            answer = next(queues[id(source)], None)
            if answer is None:
                waiting.remove(source)
                continue
            taken[id(source)].append(answer)
            turns.append(id(source))
    if rules:
        # A long rule shows the best of the clauses the search reached, so each source reads
        # its list as far as it would searched alone: what a rule shows does not hang on what
        # else was searched beside it, such as the organisation's policies.
        for source in order:
            for _ in range(wanted - len(taken[id(source)])):
                if next(queues[id(source)], None) is None:
                    break
    for held, answers in taken.items():
        taken[held] = _obliging_first(answers)
    places = dict.fromkeys(taken, 0)
    resolved = []
    for turn in turns:
        resolved.append(taken[turn][places[turn]])
        places[turn] += 1
    return resolved


def _obliging_first(answers: Sequence[_Answer]) -> list[_Answer]:
    """Within each run of equal scores, the clauses that oblige someone first."""
    ordered: list[_Answer] = []
    start = 0
    while start < len(answers):
        end = start + 1
        while end < len(answers) and answers[end].candidate.score == answers[start].candidate.score:
            end += 1
        ordered += sorted(
            answers[start:end], key=lambda answer: not answer.detail.clause.is_normative
        )
        start = end
    return ordered


def _by_clause(answers: Iterator[tuple[Fused, ClauseDetail]]) -> Iterator[_Answer]:
    for candidate, detail in answers:
        yield _Answer(candidate, detail, detail.clause.key, [detail.clause.key])


def _by_rule(answers: Iterator[tuple[Fused, ClauseDetail]]) -> Iterator[_Answer]:
    """A source's answers as rules, each where its best clause came.

    A later clause of a rule already taken joins it as reached, so what the search came to is
    known when the rule is shown. A clause with no words of its own, such as an article that is
    only a title, is passed over: what sits beneath it is found by its own words.
    """
    held: dict[str, _Answer] = {}
    for candidate, detail in answers:
        if not detail.clause.text.strip():
            continue
        rule = rule_of(detail.clause, detail.breadcrumb).key
        if rule in held:
            held[rule].reached.append(detail.clause.key)
            continue
        held[rule] = _Answer(candidate, detail, rule, [detail.clause.key])
        yield held[rule]


def _whole_rule(
    session: Session,
    answer: _Answer,
    expand: Expand,
    lang: str,
    as_of: date | None,
) -> SearchResult:
    """A rule as it comes back: its own words, what is shown beneath them, and every link
    those words state."""
    whole = get_whole(session, answer.rule, lang=lang, as_of=as_of)
    beneath, complete = shown(whole.clause, whole.beneath, answer.reached, as_of or date.today())
    links = dict.fromkeys(
        link
        for clause in [whole.clause, *beneath]
        for link in whole.cross_references.get(clause.key, ())
    )
    return SearchResult(
        clause=whole.clause,
        score=answer.candidate.score,
        ranks=answer.candidate.ranks,
        breadcrumb=whole.breadcrumb,
        cross_references=tuple(links),
        expanded=_expanded(session, whole.clause, whole.breadcrumb, expand, lang, as_of),
        beneath=beneath,
        whole=complete,
    )


def _answers(
    session: Session, candidates: Sequence[Fused], lang: str, as_of: date | None
) -> Iterator[tuple[Fused, ClauseDetail]]:
    """A source's candidates that are answers on the day asked about, in order, read from the
    database a few at a time."""
    for start in range(0, len(candidates), READ_AHEAD):
        chunk = candidates[start : start + READ_AHEAD]
        read = get_clauses(session, [candidate.key for candidate in chunk], lang=lang, as_of=as_of)
        for candidate in chunk:
            detail = read.get(candidate.key)
            if detail is None:
                continue
            # An archived policy no longer applies, and nor do words a law has ended. Both still
            # read by key, so an old citation can be checked, but nothing searches them.
            if detail.clause.archived or ended(detail.clause, as_of or date.today()):
                continue
            yield candidate, detail


def _expanded(
    session: Session,
    clause: ClauseView,
    breadcrumb: tuple[ClauseView, ...],
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

    parent = breadcrumb[-1] if breadcrumb else None
    if parent is None:
        return ()
    if expand == "parent":
        return (parent,)

    family = get_subtree(session, parent.key, lang=lang, as_of=as_of)
    return tuple(
        found for found in family if found.key != clause.key and found.depth == clause.depth
    )
