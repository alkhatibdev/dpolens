"""The eval harness, over the real pack and the real question set."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from dpolens.cli.main import app
from dpolens.engine.embedding import Embedder, get_model
from dpolens.engine.embedding.index import build_index
from dpolens.engine.evals import EvalSetError, Question, read_questions, run_set
from dpolens.engine.evals.score import answers
from dpolens.engine.packs.load import load_pack

pytestmark = pytest.mark.integration

REPO = Path(__file__).parents[2]
GDPR_PACK = REPO / "packs" / "gdpr"
TUNING = REPO / "evals" / "gdpr" / "tuning.en.yaml"
ASSISTANT = REPO / "evals" / "gdpr" / "assistant.en.yaml"


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

    run = run_set(indexed, embedder, questions, "rrf:10", pack="gdpr", question_set="tuning.en")

    assert run.score.questions == len(questions)
    assert 0.0 <= run.score.recall_at_5 <= 1.0
    assert run.score.interval.contains(run.score.recall_at_5)
    assert run.model == "e5-small"
    assert run.configuration == "rrf:10"


def test_a_run_names_the_recipe_its_vectors_were_built_with(
    indexed: Session, embedder: Embedder
) -> None:
    """So a published result says which embedded text it measured."""
    run = run_set(indexed, embedder, read_questions(TUNING)[:1], "meaning")
    built = indexed.scalars(text("SELECT DISTINCT context_recipe FROM node_embeddings")).all()

    assert built == [run.recipe]


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


def test_a_run_keeps_where_each_questions_right_clause_came(
    indexed: Session, migrated: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Written by the command and read back: every question, the clauses returned for it,
    and the place of the first that answers, which is what comparing two runs needs."""
    monkeypatch.chdir(REPO)
    monkeypatch.setenv("DPOLENS_DATABASE_URL", migrated)
    kept = tmp_path / "before" / "gdpr.json"
    runner = CliRunner()

    asked_for = ["--pack", "gdpr", "--set", "tuning.en", "--config", "meaning+normative"]
    ran = runner.invoke(app, ["evals", "run", *asked_for, "--outcomes", str(kept)])
    compared = runner.invoke(app, ["evals", "compare", str(kept), str(kept)])

    assert ran.exit_code == 0, ran.output
    record = json.loads(kept.read_text(encoding="utf-8"))
    asked = record["sets"][0]["questions"]
    assert (record["pack"], record["configuration"]) == ("gdpr", "meaning+normative")
    assert record["sets"][0]["question_set"] == "tuning.en"
    assert [question["id"] for question in asked] == [q.id for q in read_questions(TUNING)]
    for question in asked:
        assert len(question["returned"]) == 10
        answered = [
            place
            for place, key in enumerate(question["returned"], start=1)
            if any(answers(key, expected) for expected in question["expected"])
        ]
        assert question["place"] == (answered[0] if answered else None)
    assert any(question["place"] for question in asked)
    assert compared.exit_code == 0, compared.output
    assert "Not kept." in compared.output


def test_a_topic_asked_twice_is_one_item_in_the_interval(
    indexed: Session, embedder: Embedder
) -> None:
    """Two entries of one topic, one found and one not: resampled as one item the rate is a
    half every time, where two items would range from nothing to all."""
    breach = Question(
        id="breach",
        question="How quickly must a personal data breach be reported to the authority?",
        lang="en",
        expected_keys=("gdpr:no-such-clause",),
        source="https://example.org/guide",
    )
    first = run_set(indexed, embedder, [breach], "meaning+normative", pack="gdpr").outcomes[0]
    wordings = [
        replace(breach, id="found", expected_keys=(first.returned[0],), topic="breach.authority"),
        replace(breach, id="missed", topic="breach.authority"),
    ]

    run = run_set(indexed, embedder, wordings, "meaning+normative", pack="gdpr")
    apart = run_set(
        indexed,
        embedder,
        [replace(wording, topic=None) for wording in wordings],
        "meaning+normative",
        pack="gdpr",
    )

    assert [outcome.topic for outcome in run.outcomes] == ["breach.authority"] * 2
    assert (run.score.recall_at_5, str(run.score.interval)) == (0.5, "0.50 to 0.50")
    assert str(apart.score.interval) == "0.00 to 1.00"


def test_a_set_asked_in_parts_keeps_each_parts_topic_and_counts_whole_queries(
    indexed: Session, migrated: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The set in the words AI assistants send, through the command: each entry's own topic
    is what the judge reads, and a query counts once every part of it is found."""
    monkeypatch.chdir(REPO)
    monkeypatch.setenv("DPOLENS_DATABASE_URL", migrated)
    kept = tmp_path / "gdpr.json"
    questions = read_questions(ASSISTANT)
    queries = len({question.question for question in questions})

    asked_for = ["--pack", "gdpr", "--set", "assistant", "--config", "meaning+normative"]
    ran = CliRunner().invoke(app, ["evals", "run", *asked_for, "--outcomes", str(kept)])

    assert ran.exit_code == 0, ran.output
    record = json.loads(kept.read_text(encoding="utf-8"))
    assert record["sets"][0]["question_set"] == "assistant.en"
    assert [(q["id"], q["topic"]) for q in record["sets"][0]["questions"]] == [
        (question.id, question.topic) for question in questions
    ]
    assert f"gdpr assistant.en: {len(questions)} questions" in ran.output
    assert f"of {queries} queries in the top five" in " ".join(ran.output.split())


def test_a_law_loaded_alone_has_no_other_to_be_searched_beside(
    indexed: Session, migrated: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO)
    monkeypatch.setenv("DPOLENS_DATABASE_URL", migrated)

    asked_for = ["--pack", "gdpr", "--set", "tuning.en", "--config", "keyword", "--every-law"]
    ran = CliRunner().invoke(app, ["evals", "run", *asked_for])

    assert ran.exit_code == 1
    assert "gdpr is the only law loaded here" in ran.output
