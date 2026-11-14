"""A set that asks one topic in more than one entry.

The queries AI assistants send often ask two things at once, so such a set gives each thing
asked an entry of its own under the same words, and each entry names its topic.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
import yaml

from dpolens.engine.evals import Outcome, Question, queries_answered, read_questions
from dpolens.engine.evals.judge import judge, placed_in, topic_of

REPO = Path(__file__).resolve().parents[2]
SETS_NAMING_TOPICS = sorted(
    path
    for path in (REPO / "evals").glob("*/*.*.yaml")
    if any(question.topic for question in read_questions(path))
)


def asked(tmp_path: Path, *entries: dict[str, object]) -> list[Question]:
    path = tmp_path / "assistant.en.yaml"
    written = [
        {"question": "storing an address", "expected_keys": ["law:art-1"], "source": "https://x"}
        | entry
        for entry in entries
    ]
    path.write_text(yaml.safe_dump({"questions": written}), encoding="utf-8")
    return read_questions(path)


def outcome(question_id: str, found: bool, topic: str | None = None) -> Outcome:
    returned = ("law:art-1",) if found else ("law:art-2",)
    return Outcome(question_id, expected=("law:art-1",), returned=returned, topic=topic)


def test_the_repository_has_a_set_that_names_topics() -> None:
    """A pattern that matched nothing would pass the checks of those sets without checking."""
    assert REPO / "evals" / "gdpr" / "assistant.en.yaml" in SETS_NAMING_TOPICS


def test_a_question_names_its_topic(tmp_path: Path) -> None:
    named, unnamed = asked(tmp_path, {"id": "address.kept-2", "topic": "address.kept"}, {"id": "b"})

    assert (named.topic, unnamed.topic) == ("address.kept", None)


def test_the_topic_a_question_names_is_its_topic() -> None:
    assert topic_of("address.kept-2", "address.kept") == "address.kept"
    assert topic_of("retention-chat") == "retention"
    assert topic_of("retention-chat", None) == "retention"


def test_one_part_asked_in_two_wordings_is_one_topic_to_the_judge() -> None:
    def record(place: int | None) -> dict[str, object]:
        questions = [
            {"id": "address.kept", "topic": "address.kept", "place": place},
            {"id": "address.kept-2", "topic": "address.kept", "place": place},
        ]
        return {"pack": "law", "sets": [{"question_set": "assistant.en", "questions": questions}]}

    judgement = judge(placed_in(record(None)), placed_in(record(1)))

    assert (judgement.questions, judgement.topics) == (2, 1)


def test_a_query_is_answered_when_each_of_its_parts_is(tmp_path: Path) -> None:
    questions = asked(
        tmp_path,
        {"id": "a.kept", "question": "keeping and protecting an address"},
        {"id": "a.protected", "question": "keeping and protecting an address"},
        {"id": "b.kept", "question": "keeping and sharing an address"},
        {"id": "b.shared", "question": "keeping and sharing an address"},
    )
    outcomes = [
        outcome("a.kept", found=True),
        outcome("a.protected", found=True),
        outcome("b.kept", found=True),
        outcome("b.shared", found=False),
    ]

    assert queries_answered(questions, outcomes, 5) == (1, 2)


def test_a_part_found_below_the_top_k_is_not_answered_in_it(tmp_path: Path) -> None:
    questions = asked(tmp_path, {"id": "a"})
    sixth = Outcome("a", expected=("law:art-1",), returned=(*["law:art-2"] * 5, "law:art-1"))

    assert queries_answered(questions, [sixth], 5) == (0, 1)
    assert queries_answered(questions, [sixth], 10) == (1, 1)


@pytest.mark.parametrize(
    "path", SETS_NAMING_TOPICS, ids=lambda path: f"{path.parent.name}/{path.name}"
)
def test_every_entry_of_a_topic_expects_the_same_clauses(path: Path) -> None:
    """One topic is one thing asked, so it has one label however it is worded."""
    labels = defaultdict(set)
    for question in read_questions(path):
        labels[question.topic].add(question.expected_keys)

    assert {topic: found for topic, found in labels.items() if len(found) > 1} == {}


@pytest.mark.parametrize(
    "path", SETS_NAMING_TOPICS, ids=lambda path: f"{path.parent.name}/{path.name}"
)
def test_the_parts_of_a_query_are_different_topics(path: Path) -> None:
    """An entry that repeated a part would count one thing asked twice."""
    parts = defaultdict(list)
    for question in read_questions(path):
        parts[question.question].append(question.topic)

    assert {words: found for words, found in parts.items() if len(found) != len(set(found))} == {}
