"""The eval harness, over the real pack and the real question set."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dpolens.engine.embedding import Embedder, get_model
from dpolens.engine.embedding.index import build_index
from dpolens.engine.evals import EvalSetError, read_questions, run_set
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration

REPO = Path(__file__).parents[2]
GDPR_PACK = REPO / "packs" / "gdpr"
TUNING = REPO / "evals" / "gdpr" / "tuning.yaml"


@pytest.fixture(scope="session")
def embedder() -> Iterator[Embedder]:
    with Embedder(get_model("e5-small")) as loaded:
        yield loaded


@pytest.fixture(scope="module")
def indexed(
    engine: Engine, embedder: Embedder, truncate_corpus: Callable[[], None]
) -> Iterator[Session]:
    """Load and index the real pack once for this module.

    Embedding 958 clauses takes half a minute, and every test here only reads,
    so paying it per test would make the suite too slow to run often.
    """
    with Session(engine) as prepared:
        load_pack(prepared, GDPR_PACK)
        prepared.commit()
        build_index(prepared, embedder)
        prepared.commit()
        yield prepared

    truncate_corpus()


def test_every_question_names_a_source() -> None:
    """A question with no source is a guess about what should match."""
    questions = read_questions(TUNING)

    assert len(questions) >= 15
    assert all(question.source.startswith("https://") for question in questions)


def test_every_expected_clause_exists_in_the_pack(indexed: Session) -> None:
    """A typo in an expected key would show up as a permanent miss."""
    keys = {key for question in read_questions(TUNING) for key in question.expected_keys}
    present = set(
        indexed.scalars(
            text(
                "SELECT canonical_key FROM document_nodes WHERE canonical_key = ANY(:keys)"
            ).bindparams(keys=list(keys))
        ).all()
    )

    assert keys - present == set()


def test_a_question_set_without_sources_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text(
        "questions:\n  - id: a\n    question: why\n    expected_keys: [x:1]\n", encoding="utf-8"
    )

    with pytest.raises(EvalSetError, match="missing source"):
        read_questions(path)


def test_an_empty_question_set_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("questions: []\n", encoding="utf-8")

    with pytest.raises(EvalSetError, match="no questions"):
        read_questions(path)


def test_a_run_scores_every_question(indexed: Session, embedder: Embedder) -> None:
    questions = read_questions(TUNING)

    run = run_set(indexed, embedder, questions, "rrf:10", pack="gdpr", question_set="tuning")

    assert run.score.questions == len(questions)
    assert 0.0 <= run.score.recall_at_5 <= 1.0
    assert run.score.interval.contains(run.score.recall_at_5)
    assert run.model == "e5-small"
    assert run.configuration == "rrf:10"


def test_baselines_are_scored_the_same_way(indexed: Session, embedder: Embedder) -> None:
    """A fusion rule must never be adopted while being worse than half the system."""
    questions = read_questions(TUNING)

    keyword = run_set(indexed, embedder, questions, "keyword")
    meaning = run_set(indexed, embedder, questions, "meaning")

    assert keyword.score.questions == meaning.score.questions == len(questions)
    assert keyword.score.recall_at_5 >= 0
    assert meaning.score.recall_at_5 > keyword.score.recall_at_5, (
        "meaning search beat keyword on this corpus when this was written; "
        "if that has changed, the comparison in docs needs revisiting"
    )


def test_excluding_explaining_text_is_measurable(indexed: Session, embedder: Embedder) -> None:
    """Recitals crowd out the articles that oblige someone, and the harness can
    show it rather than the question being argued."""
    questions = read_questions(TUNING)

    everything = run_set(indexed, embedder, questions, "meaning")
    normative = run_set(indexed, embedder, questions, "meaning+normative")

    assert normative.score.recall_at_5 >= everything.score.recall_at_5
