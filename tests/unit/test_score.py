"""Scoring retrieval.

The arithmetic behind the published number, tested on hand-built outcomes so it
does not depend on what search happens to return today.
"""

from __future__ import annotations

from dpolens.engine.evals.score import (
    Outcome,
    answers,
    bootstrap_interval,
    mean_reciprocal_rank,
    recall_at,
    score,
)


def outcome(question_id: str, expected: str, *returned: str) -> Outcome:
    return Outcome(question_id=question_id, expected=(expected,), returned=returned)


def test_a_clause_inside_the_expected_one_answers_it() -> None:
    """A point of Article 13(1) is part of Article 13(1)."""
    assert answers("gdpr:art-13:para-1", "gdpr:art-13:para-1")
    assert answers("gdpr:art-13:para-1:pt-b", "gdpr:art-13:para-1")


def test_a_sibling_or_a_broader_clause_does_not() -> None:
    assert not answers("gdpr:art-13:para-2", "gdpr:art-13:para-1")
    assert not answers("gdpr:art-13", "gdpr:art-13:para-1")
    assert not answers("gdpr:art-130:para-1", "gdpr:art-13:para-1")


def test_recall_counts_questions_not_results() -> None:
    outcomes = [
        outcome("a", "x:1", "x:1", "y:1"),
        outcome("b", "x:2", "y:1", "y:2", "y:3", "y:4", "y:5", "x:2"),
    ]

    assert recall_at(outcomes, 5) == 0.5
    assert recall_at(outcomes, 10) == 1.0


def test_reciprocal_rank_rewards_being_first() -> None:
    first = [outcome("a", "x:1", "x:1", "y:1")]
    third = [outcome("a", "x:1", "y:1", "y:2", "x:1")]

    assert mean_reciprocal_rank(first) == 1.0
    assert mean_reciprocal_rank(third) == 1 / 3


def test_a_question_that_never_hits_scores_zero() -> None:
    outcomes = [outcome("a", "x:1", "y:1", "y:2")]

    assert recall_at(outcomes, 10) == 0.0
    assert mean_reciprocal_rank(outcomes) == 0.0


def test_the_interval_is_wide_on_a_small_set() -> None:
    """This is why fifty questions are required before publishing a number."""
    outcomes = [outcome(f"q{n}", "x:1", "x:1") for n in range(7)]
    outcomes += [outcome(f"m{n}", "x:1", "y:1") for n in range(8)]

    interval = bootstrap_interval(outcomes, k=5)

    assert interval.contains(recall_at(outcomes, 5))
    assert interval.high - interval.low > 0.2


def test_the_interval_is_repeatable() -> None:
    """CI compares runs, so the interval cannot move on its own."""
    outcomes = [outcome(f"q{n}", "x:1", "x:1" if n % 2 else "y:1") for n in range(20)]

    first = bootstrap_interval(outcomes)
    second = bootstrap_interval(outcomes)

    assert (first.low, first.high) == (second.low, second.high)


def test_a_perfect_set_has_no_spread() -> None:
    outcomes = [outcome(f"q{n}", "x:1", "x:1") for n in range(10)]

    interval = bootstrap_interval(outcomes)

    assert (interval.low, interval.high) == (1.0, 1.0)


def test_score_reports_what_failed() -> None:
    outcomes = [outcome("found", "x:1", "x:1"), outcome("lost", "x:2", "y:9")]

    result = score(outcomes)

    assert result.questions == 2
    assert result.recall_at_5 == 0.5
    assert result.misses == ("lost",)


def test_the_gate_fires_only_below_the_published_interval() -> None:
    """A fifty-question set moves a few points on its own. A gate that fires on
    that gets switched off, which is worse than no gate."""
    from dpolens.engine.evals.gate import compare

    published = {"recall_at_5": 0.78, "interval": [0.63, 0.89]}

    assert not compare("gdpr", 0.78, published).is_regression
    assert not compare("gdpr", 0.70, published).is_regression, "inside the interval"
    assert not compare("gdpr", 0.63, published).is_regression, "exactly at the floor"
    assert compare("gdpr", 0.60, published).is_regression


def test_the_verdict_reads_as_a_sentence() -> None:
    from dpolens.engine.evals.gate import compare

    verdict = compare("gdpr", 0.60, {"recall_at_5": 0.78, "interval": [0.63, 0.89]})

    assert "REGRESSION" in str(verdict)
    assert "0.60" in str(verdict)
