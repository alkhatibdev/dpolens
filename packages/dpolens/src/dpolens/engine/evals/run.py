"""Running a question set against retrieval.

Every configuration is scored the same way, including the two single-retriever
baselines. Those are not decoration: on the first four questions tried by hand,
meaning search alone beat both fusion rules, and a matrix without baselines
could adopt a fusion rule that is worse than half the system.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.evals.score import Outcome, Score, score
from dpolens.engine.packs.selection import Scope, scope_for
from dpolens.engine.search.engine import CANDIDATE_DEPTH, search
from dpolens.engine.search.fuse import Fused, Fusion, fuse
from dpolens.engine.search.keyword import ALTERNATIVES, Candidate, KeywordIndex, keyword_search
from dpolens.engine.search.rerank import Reranker, rerank
from dpolens.engine.search.vector import vector_search

DEPTH = 10
"""How many results each question is scored over. recall@5 needs at least five,
and recall@10 is reported alongside it."""


class EvalSetError(Exception):
    """A question set is not usable as written."""


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    lang: str
    expected_keys: tuple[str, ...]
    source: str
    note: str | None = None


@dataclass(frozen=True)
class Run:
    pack: str
    question_set: str
    configuration: str
    model: str
    recipe: str
    score: Score
    outcomes: tuple[Outcome, ...]


def read_questions(path: Path) -> list[Question]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("questions") or []
    if not entries:
        raise EvalSetError(f"{path} holds no questions")

    questions = []
    for entry in entries:
        missing = [
            field for field in ("id", "question", "expected_keys", "source") if not entry.get(field)
        ]
        if missing:
            raise EvalSetError(
                f"{path}: question {entry.get('id', '?')} is missing {', '.join(missing)}. "
                "Every question names the guidance that ties it to a clause."
            )
        questions.append(
            Question(
                id=str(entry["id"]),
                question=str(entry["question"]),
                lang=str(entry.get("lang", "en")),
                expected_keys=tuple(entry["expected_keys"]),
                source=str(entry["source"]),
                note=entry.get("note"),
            )
        )

    repeated = {question.id for question in questions}
    if len(repeated) != len(questions):
        raise EvalSetError(f"{path}: two questions share an id")
    return questions


def run_set(
    session: Session,
    embedder: Embedder,
    questions: list[Question],
    configuration: str = "rrf:10",
    pack: str = "",
    question_set: str = "",
    reranker: Reranker | None = None,
) -> Run:
    """Score one configuration over one question set.

    A configuration is a fusion rule ("rrf:10", "convex:0.5") or a single
    retriever ("keyword", "meaning"), so baselines and fusion rules are reported
    in the same units. Modifiers follow it: "+normative" drops text that
    explains without obliging, "+light", "+snowball" or "+folded-snowball" picks
    the Arabic keyword index, and "+rerank25" rescores the top 25 with the
    cross-encoder passed as `reranker`.

    A run for a pack searches that pack's law alone, whatever else is loaded or
    selected, so its score means that law. Without a pack it searches what any
    search would.
    """
    check_configuration(configuration, reranker)
    scope = scope_for(session, [pack]) if pack else None
    outcomes = []
    for question in questions:
        returned = _retrieve(session, embedder, question, configuration, reranker, scope)
        outcomes.append(
            Outcome(
                question_id=question.id,
                expected=question.expected_keys,
                returned=tuple(returned),
            )
        )

    return Run(
        pack=pack,
        question_set=question_set,
        configuration=configuration,
        model=embedder.model.name,
        recipe="v1",
        score=score(outcomes),
        outcomes=tuple(outcomes),
    )


def run_together(runs: Sequence[Run]) -> Run:
    """Several sets scored as one, such as a law's topics asked in Arabic and in English.

    A question id names one topic in every set, so its outcomes are resampled
    together: nineteen topics asked twice are nineteen items, not thirty-eight,
    and the interval is as wide as nineteen items make it.
    """
    first = runs[0]
    if any(
        (run.pack, run.configuration, run.model) != (first.pack, first.configuration, first.model)
        for run in runs
    ):
        raise ValueError("only runs of one pack, configuration and model are scored together")

    outcomes = tuple(
        Outcome(
            question_id=f"{run.question_set}/{outcome.question_id}",
            expected=outcome.expected,
            returned=outcome.returned,
        )
        for run in runs
        for outcome in run.outcomes
    )
    return Run(
        pack=first.pack,
        question_set="+".join(run.question_set for run in runs),
        configuration=first.configuration,
        model=first.model,
        recipe=first.recipe,
        score=score(outcomes, group_of=lambda outcome: outcome.question_id.split("/", 1)[1]),
        outcomes=outcomes,
    )


def _retrieve(
    session: Session,
    embedder: Embedder,
    question: Question,
    configuration: str,
    reranker: Reranker | None = None,
    scope: Scope | None = None,
) -> list[str]:
    base, modifiers = _parse(configuration)
    normative_only = "normative" in modifiers
    depth = _rerank_depth(modifiers)
    indexes = _keyword_indexes(modifiers)
    packs = list(scope.laws) if scope is not None and scope.narrowed else None

    if base in ("keyword", "meaning"):
        found = (
            keyword_search(
                session,
                question.question,
                lang=question.lang,
                limit=CANDIDATE_DEPTH,
                normative_only=normative_only,
                indexes=indexes,
                packs=packs,
            )
            if base == "keyword"
            else vector_search(
                session,
                embedder,
                question.question,
                limit=CANDIDATE_DEPTH,
                normative_only=normative_only,
                packs=packs,
            )
        )
        if depth and reranker is not None:
            rescored = _reranked(
                session, reranker, question, {base: found}, Fusion.parse("rrf:10"), depth
            )
            return [candidate.key for candidate in rescored[:DEPTH]]
        return [candidate.key for candidate in found[:DEPTH]]

    fusion = Fusion.parse(base)
    if depth and reranker is not None:
        lists = {
            "keyword": keyword_search(
                session,
                question.question,
                lang=question.lang,
                limit=CANDIDATE_DEPTH,
                normative_only=normative_only,
                indexes=indexes,
                packs=packs,
            ),
            "meaning": vector_search(
                session,
                embedder,
                question.question,
                limit=CANDIDATE_DEPTH,
                normative_only=normative_only,
                packs=packs,
            ),
        }
        fused = _reranked(session, reranker, question, lists, fusion, depth)
        return [candidate.key for candidate in fused[:DEPTH]]

    results = search(
        session,
        embedder,
        question.question,
        limit=DEPTH,
        lang=question.lang,
        fusion=fusion,
        normative_only=normative_only,
        keyword_indexes=indexes,
        scope=scope,
    )
    return [result.clause.key for result in results]


MODIFIERS = frozenset({"normative", *ALTERNATIVES})
"""The modifiers a configuration can carry, besides +rerank and its depth."""

RERANK = re.compile(r"rerank\d*")


def check_configuration(configuration: str, reranker: Reranker | None = None) -> None:
    """Refuse a configuration that would not run as written.

    A modifier nothing reads, two of a kind where one is used, or +rerank with
    no reranker would each score something else, and report it under the name
    that was asked for.
    """
    base, modifiers = _parse(configuration)
    if base not in ("keyword", "meaning"):
        Fusion.parse(base)

    unknown = sorted(
        f"+{modifier}" for modifier in modifiers - MODIFIERS if not RERANK.fullmatch(modifier)
    )
    if unknown:
        known = ", ".join(f"+{modifier}" for modifier in sorted(MODIFIERS))
        raise ValueError(
            f"{configuration!r} has a modifier nothing reads: {', '.join(unknown)}. "
            f"The modifiers are {known}, and +rerank with a depth, such as +rerank25"
        )

    # A set has no order, so with two of a kind, which one is used would vary by run.
    for kind, chosen in (
        ("keyword index", modifiers & ALTERNATIVES.keys()),
        ("rerank depth", {modifier for modifier in modifiers if RERANK.fullmatch(modifier)}),
    ):
        if len(chosen) > 1:
            listed = ", ".join(f"+{modifier}" for modifier in sorted(chosen))
            raise ValueError(f"{configuration!r} names more than one {kind}: {listed}")

    if _rerank_depth(modifiers) and reranker is None:
        raise ValueError(f"{configuration!r} asks for reranking, and no reranker was given")


def _parse(configuration: str) -> tuple[str, set[str]]:
    base, *modifiers = configuration.split("+")
    return base, set(modifiers)


def _keyword_indexes(modifiers: set[str]) -> dict[str, KeywordIndex]:
    """The keyword indexes a run swaps in, such as `+snowball` for Arabic."""
    chosen: dict[str, KeywordIndex] = {}
    for modifier in modifiers:
        chosen.update(ALTERNATIVES.get(modifier, {}))
    return chosen


def _rerank_depth(modifiers: set[str]) -> int:
    for modifier in modifiers:
        if modifier.startswith("rerank"):
            return int(modifier.removeprefix("rerank") or 25)
    return 0


def _reranked(
    session: Session,
    reranker: Reranker,
    question: Question,
    lists: Mapping[str, Sequence[Candidate]],
    fusion: Fusion,
    depth: int,
) -> list[Fused]:
    """Fuse, then rescore the head with the cross-encoder."""
    fused = fuse(lists, fusion)
    head = fused[:depth]
    texts = _texts_for(session, [candidate.key for candidate in head])
    return rerank(reranker, question.question, fused, texts, depth=depth)


def _texts_for(session: Session, keys: list[str]) -> dict[str, str]:
    """The text a cross-encoder reads, which is what a person would read."""
    if not keys:
        return {}
    rows = session.execute(
        text(
            """
            SELECT n.canonical_key AS key,
                   coalesce(t.heading, '') || ' ' || t.body_text AS body
            FROM document_nodes n
            JOIN node_texts t ON t.node_id = n.id
            WHERE n.canonical_key = ANY(:keys)
            """
        ),
        {"keys": keys},
    ).all()
    return {row.key: row.body for row in rows}
