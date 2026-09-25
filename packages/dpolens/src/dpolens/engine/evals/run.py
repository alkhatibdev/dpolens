"""Running a question set against retrieval.

Every configuration is scored the same way, including the two single-retriever
baselines. Those are not decoration: on the first four questions tried by hand,
meaning search alone beat both fusion rules, and a matrix without baselines
could adopt a fusion rule that is worse than half the system.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.evals.score import Outcome, Score, score
from dpolens.engine.search.engine import CANDIDATE_DEPTH, search
from dpolens.engine.search.fuse import Fusion
from dpolens.engine.search.keyword import keyword_search
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
) -> Run:
    """Score one configuration over one question set.

    The configuration is either a fusion rule ("rrf:10", "convex:0.5") or a
    single retriever ("keyword", "meaning"), so baselines and fusion rules are
    reported in the same units.
    """
    outcomes = []
    for question in questions:
        returned = _retrieve(session, embedder, question, configuration)
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
    session: Session, embedder: Embedder, question: Question, configuration: str
) -> list[str]:
    # A "+normative" suffix drops recitals and other explaining text, which is
    # the hypothesis that they crowd out the articles that oblige someone.
    configuration, _, modifier = configuration.partition("+")
    normative_only = modifier == "normative"

    if configuration == "keyword":
        found = keyword_search(
            session,
            question.question,
            lang=question.lang,
            limit=CANDIDATE_DEPTH,
            normative_only=normative_only,
        )
        return [candidate.key for candidate in found[:DEPTH]]

    if configuration == "meaning":
        found = vector_search(
            session,
            embedder,
            question.question,
            limit=CANDIDATE_DEPTH,
            normative_only=normative_only,
        )
        return [candidate.key for candidate in found[:DEPTH]]

    results = search(
        session,
        embedder,
        question.question,
        limit=DEPTH,
        lang=question.lang,
        fusion=Fusion.parse(configuration),
        normative_only=normative_only,
    )
    return [result.clause.key for result in results]
