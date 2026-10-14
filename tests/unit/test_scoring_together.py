"""Scoring one law's topics asked in two languages as one score.

A topic asked in Arabic and in English is one item measured twice. Counted as
two, the interval would claim the precision of twice as many topics.
"""

from __future__ import annotations

import pytest

from dpolens.engine.evals import Run, run_together
from dpolens.engine.evals.score import Outcome, score


def outcome(question_id: str, hit: bool) -> Outcome:
    return Outcome(
        question_id=question_id,
        expected=("law:art-1",),
        returned=("law:art-1",) if hit else ("law:art-9",),
    )


def a_run(question_set: str, hits: list[bool], configuration: str = "convex:0.5") -> Run:
    outcomes = tuple(outcome(f"topic-{number}", hit) for number, hit in enumerate(hits))
    return Run(
        pack="law",
        question_set=question_set,
        configuration=configuration,
        model="e5-small",
        recipe="v1",
        score=score(outcomes),
        outcomes=outcomes,
    )


HITS = [True, False, True, True, False, True, False, True, True, True]


def test_a_topic_asked_twice_counts_once_in_the_interval() -> None:
    once = a_run("held_out", HITS)
    together = run_together([once, a_run("held_out.en", HITS)])

    assert together.score.questions == 2 * len(HITS)
    assert together.score.recall_at_5 == once.score.recall_at_5
    assert together.score.interval == once.score.interval


def test_counted_separately_the_same_answers_would_claim_more_precision() -> None:
    doubled = score([*a_run("a", HITS).outcomes, *a_run("b", HITS).outcomes])
    once = a_run("held_out", HITS).score

    assert doubled.interval.high - doubled.interval.low < once.interval.high - once.interval.low


def test_the_sets_are_named_and_each_miss_says_which_set_it_is_from() -> None:
    together = run_together([a_run("held_out", [True, False]), a_run("held_out.en", [False, True])])

    assert together.question_set == "held_out+held_out.en"
    assert together.score.misses == ("held_out/topic-1", "held_out.en/topic-0")


def test_runs_of_different_configurations_are_not_scored_together() -> None:
    with pytest.raises(ValueError, match="one pack, configuration and model"):
        run_together([a_run("held_out", HITS), a_run("held_out.en", HITS, "rrf:10")])
