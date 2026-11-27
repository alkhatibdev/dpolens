"""Scoring one law's topics asked in two languages as one score.

A topic asked in Arabic and in English is one item measured twice. Counted as
two, the interval would claim the precision of twice as many topics.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from dpolens.engine.evals import Run, run_together
from dpolens.engine.evals.score import Outcome, score


def outcome(question_id: str, hit: bool) -> Outcome:
    return Outcome(
        question_id=question_id,
        expected=("law:art-1",),
        returned=("law:art-1",) if hit else ("law:art-9",),
    )


def a_run(
    question_set: str,
    hits: list[bool],
    configuration: str = "convex:0.5",
    beside: tuple[str, ...] = (),
) -> Run:
    outcomes = tuple(outcome(f"topic-{number}", hit) for number, hit in enumerate(hits))
    return Run(
        pack="law",
        question_set=question_set,
        configuration=configuration,
        model="e5-small",
        recipe="v1",
        score=score(outcomes),
        outcomes=outcomes,
        beside=beside,
    )


HITS = [True, False, True, True, False, True, False, True, True, True]


def test_a_topic_asked_twice_counts_once_in_the_interval() -> None:
    once = a_run("held_out.ar", HITS)
    together = run_together([once, a_run("held_out.en", HITS)])

    assert together.score.questions == 2 * len(HITS)
    assert together.score.recall_at_5 == once.score.recall_at_5
    assert together.score.interval == once.score.interval


def test_counted_separately_the_same_answers_would_claim_more_precision() -> None:
    doubled = score([*a_run("a", HITS).outcomes, *a_run("b", HITS).outcomes])
    once = a_run("held_out.ar", HITS).score

    assert doubled.interval.high - doubled.interval.low < once.interval.high - once.interval.low


def test_the_sets_are_named_and_each_miss_says_which_set_it_is_from() -> None:
    together = run_together(
        [a_run("held_out.ar", [True, False]), a_run("held_out.en", [False, True])]
    )

    assert together.question_set == "held_out.ar+held_out.en"
    assert together.score.misses == ("held_out.ar/topic-1", "held_out.en/topic-0")


def test_runs_of_different_configurations_are_not_scored_together() -> None:
    with pytest.raises(ValueError, match="one pack, configuration and model"):
        run_together([a_run("held_out.ar", HITS), a_run("held_out.en", HITS, "rrf:10")])


def test_a_run_beside_other_laws_is_named_with_them() -> None:
    assert a_run("tuning.ar", HITS).name == "tuning.ar"
    assert a_run("tuning.ar", HITS, beside=("gdpr", "sa-pdpl")).name == (
        "tuning.ar beside gdpr, sa-pdpl"
    )


def test_sets_scored_together_beside_other_laws_keep_saying_which() -> None:
    together = run_together(
        [a_run("tuning.ar", HITS, beside=("gdpr",)), a_run("tuning.en", HITS, beside=("gdpr",))]
    )

    assert together.name == "tuning.ar+tuning.en beside gdpr"


def test_a_law_alone_and_beside_others_are_not_scored_together() -> None:
    with pytest.raises(ValueError, match="searched beside the same laws"):
        run_together([a_run("tuning.ar", HITS), a_run("tuning.en", HITS, beside=("gdpr",))])


def test_a_whole_rule_counts_by_the_clauses_it_showed_when_sets_are_scored_together() -> None:
    # The rule's key is Article 1; the question expects its paragraph 2, which it showed.
    rule = Outcome(
        question_id="q1",
        expected=("law:art-1:para-2",),
        returned=("law:art-1",),
        shown=(("law:art-1", "law:art-1:para-1", "law:art-1:para-2"),),
    )
    alone = Run(
        pack="law",
        question_set="held_out.ar",
        configuration="convex:0.5+rules",
        model="e5-small",
        recipe="v1",
        score=score((rule,)),
        outcomes=(rule,),
    )

    together = run_together([alone, replace(alone, question_set="held_out.en")])

    assert alone.score.recall_at_5 == 1.0
    assert together.score.recall_at_5 == 1.0


def test_where_sets_name_topics_the_topic_is_what_the_interval_resamples() -> None:
    def parts(question_set: str) -> Run:
        # Each topic asked in both languages, under ids that differ from one set to the other.
        outcomes = tuple(
            replace(outcome(f"{question_set}-{number}", hit), topic=f"topic-{number}")
            for number, hit in enumerate(HITS)
        )
        return Run(
            pack="law",
            question_set=question_set,
            configuration="convex:0.5",
            model="e5-small",
            recipe="v1",
            score=score(outcomes),
            outcomes=outcomes,
        )

    together = run_together([parts("held_out.ar"), parts("held_out.en")])

    assert together.score.interval == a_run("held_out.ar", HITS).score.interval
