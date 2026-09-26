"""Running a question set against retrieval.

Every configuration is scored the same way, including the two single-retriever
baselines. Those are not decoration: on the first four questions tried by hand,
meaning search alone beat both fusion rules, and a matrix without baselines
could adopt a fusion rule that is worse than half the system.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.evals.score import Outcome, Score, score
from dpolens.engine.search.engine import CANDIDATE_DEPTH, search
from dpolens.engine.search.fuse import Fused, Fusion, fuse
from dpolens.engine.search.keyword import Candidate, keyword_search
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
    explains without obliging, and "+rerank25" rescores the top 25 with a
    cross-encoder.
    """
    outcomes = []
    for question in questions:
        returned = _retrieve(session, embedder, question, configuration, reranker)
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


def _retrieve(
    session: Session,
    embedder: Embedder,
    question: Question,
    configuration: str,
    reranker: Reranker | None = None,
) -> list[str]:
    base, modifiers = _parse(configuration)
    normative_only = "normative" in modifiers
    depth = _rerank_depth(modifiers)

    if base in ("keyword", "meaning"):
        found = (
            keyword_search(
                session,
                question.question,
                lang=question.lang,
                limit=CANDIDATE_DEPTH,
                normative_only=normative_only,
            )
            if base == "keyword"
            else vector_search(
                session,
                embedder,
                question.question,
                limit=CANDIDATE_DEPTH,
                normative_only=normative_only,
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
            ),
            "meaning": vector_search(
                session,
                embedder,
                question.question,
                limit=CANDIDATE_DEPTH,
                normative_only=normative_only,
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
    )
    return [result.clause.key for result in results]


def _parse(configuration: str) -> tuple[str, set[str]]:
    base, *modifiers = configuration.split("+")
    return base, set(modifiers)


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
