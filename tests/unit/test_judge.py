"""Judging a change to search.

The arithmetic behind "kept" and "not kept", on hand-built runs, so it does not depend on
what search happens to return today.
"""

from __future__ import annotations

import pytest

from dpolens.engine.evals.judge import (
    Placed,
    Unpaired,
    chance_of_gain,
    judge,
    placed_in,
    topic_of,
)


def run(
    places: dict[str, int | None], question_set: str = "tuning.en", pack: str = "law"
) -> list[Placed]:
    return [
        Placed(pack, question_set, question_id, topic_of(question_id), place)
        for question_id, place in places.items()
    ]


def topics(count: int, place: int | None) -> dict[str, int | None]:
    return {f"topic-{number}": place for number in range(count)}


def test_a_place_scores_by_how_high_it_is() -> None:
    assert Placed("law", "tuning.en", "a", "a", 1).score == 1.0
    assert Placed("law", "tuning.en", "a", "a", 4).score == 0.25
    assert Placed("law", "tuning.en", "a", "a", 10).score == 0.1
    assert Placed("law", "tuning.en", "a", "a", None).score == 0.0
    assert Placed("law", "tuning.en", "a", "a", 5).hit
    assert not Placed("law", "tuning.en", "a", "a", 6).hit


def test_a_chat_question_shares_its_topic() -> None:
    assert topic_of("erasure-chat") == "erasure"
    assert topic_of("erasure") == "erasure"


def test_nothing_changing_is_not_a_gain() -> None:
    same = run(topics(20, 3))

    judged = judge(same, same)

    assert judged.chance == 1.0
    assert not judged.kept
    assert (judged.topics_found, judged.topics_lost) == (0, 0)


def test_a_gain_on_many_topics_is_kept() -> None:
    judged = judge(run(topics(20, None)), run(topics(20, 1)))

    assert judged.kept
    assert judged.chance < 0.001
    assert (judged.hits_before, judged.hits_after) == (0, 20)
    assert (judged.topics_found, judged.topics_lost) == (20, 0)
    assert (judged.score_before, judged.score_after) == (0.0, 1.0)


def test_a_gain_on_three_topics_is_what_chance_gives_one_time_in_eight() -> None:
    """Three changes all upward is one of the eight ways three signs can fall."""
    before = run({**topics(20, 3), "a": None, "b": None, "c": None})
    after = run({**topics(20, 3), "a": 1, "b": 1, "c": 1})

    judged = judge(before, after)

    assert judged.chance == pytest.approx(0.125, abs=0.02)
    assert not judged.kept


def test_a_topic_asked_many_ways_counts_once() -> None:
    """Three topics, each asked formally and as chat in two languages, are three topics:
    twelve questions moving together are not twelve gains."""
    ways = [
        (f"{topic}{style}", language)
        for topic in "abc"
        for style in ("", "-chat")
        for language in ("ar", "en")
    ]
    before = [
        Placed("law", f"tuning.{language}", question, topic_of(question), None)
        for question, language in ways
    ]
    after = [
        Placed("law", f"tuning.{language}", question, topic_of(question), 1)
        for question, language in ways
    ]

    judged = judge(before, after)

    assert judged.questions == 12
    assert judged.topics == 3
    assert judged.chance == pytest.approx(0.125, abs=0.02)
    assert not judged.kept


def test_a_clause_that_climbs_inside_the_top_five_counts() -> None:
    """Hits at five do not change, and the right clauses sit higher."""
    judged = judge(run(topics(20, 5)), run(topics(20, 1)))

    assert (judged.hits_before, judged.hits_after) == (20, 20)
    assert judged.kept


def test_a_set_that_loses_more_than_chance_explains_stops_the_change() -> None:
    before = run(topics(40, None), "tuning.en") + run(topics(20, 1), "tuning.ar")
    after = run(topics(40, 1), "tuning.en") + run(topics(20, None), "tuning.ar")

    judged = judge(before, after)
    worse = {change.question_set: change.worse for change in judged.sets}

    assert judged.score_after > judged.score_before
    assert worse == {"tuning.en": False, "tuning.ar": True}
    assert not judged.kept


def test_a_set_that_slips_by_one_question_is_not_called_worse() -> None:
    before = run(topics(40, None), "tuning.en") + run(topics(20, 5), "tuning.ar")
    slipped = {**topics(20, 5), "topic-0": 6}
    after = run(topics(40, 1), "tuning.en") + run(slipped, "tuning.ar")

    judged = judge(before, after)
    arabic = next(change for change in judged.sets if change.question_set == "tuning.ar")

    assert (arabic.hits_before, arabic.hits_after) == (20, 19)
    assert not arabic.worse
    assert judged.kept


def test_runs_over_different_questions_are_refused() -> None:
    with pytest.raises(Unpaired, match=r"1 in one run only, such as law/tuning\.en/b"):
        judge(run({"a": 1, "b": 2}), run({"a": 1}))


def test_a_run_that_holds_a_question_twice_is_refused() -> None:
    once = run({"a": 1, "b": 2})

    with pytest.raises(Unpaired, match="holds a question twice"):
        judge(once + run({"a": 3}), once)


def test_judging_twice_gives_the_same_answer() -> None:
    changes = [0.5, -0.2, 0.9, 0.1, -0.4, 0.3, 0.75]

    assert chance_of_gain(changes) == chance_of_gain(changes)


def test_an_outcomes_file_is_read_question_by_question() -> None:
    record = {
        "pack": "law",
        "sets": [
            {
                "question_set": "tuning.ar",
                "questions": [
                    {"id": "erasure", "topic": "erasure", "place": 2},
                    {"id": "erasure-chat", "topic": "erasure", "place": None},
                ],
            }
        ],
    }

    assert placed_in(record) == [
        Placed("law", "tuning.ar", "erasure", "erasure", 2),
        Placed("law", "tuning.ar", "erasure-chat", "erasure", None),
    ]
