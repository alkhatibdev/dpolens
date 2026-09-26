"""Scoring retrieval.

Recall@k asks the question an assistant actually cares about: was the right
clause in the handful it was shown. It is reported with a confidence interval,
because a fifty-question set is small and a bare number invites more confidence
than it has earned. On thirty questions, one question is more than three points.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

CONFIDENCE = 0.95
RESAMPLES = 2000


def answers(returned: str, expected: str) -> bool:
    """Whether a returned clause answers what was expected.

    The expected key counts, and so does anything inside it: a point of
    Article 13(1) is part of Article 13(1), and an assistant shown that point
    has found the provision. A sibling paragraph does not count, because
    Article 13(2) is a different rule from Article 13(1).
    """
    return returned == expected or returned.startswith(f"{expected}:")


@dataclass(frozen=True)
class Outcome:
    """What retrieval did with one question."""

    question_id: str
    expected: tuple[str, ...]
    returned: tuple[str, ...]

    def hit_at(self, k: int) -> bool:
        return any(
            answers(candidate, key) for candidate in self.returned[:k] for key in self.expected
        )

    @property
    def first_hit(self) -> int | None:
        """The position of the first clause that answers, counting from one."""
        for position, candidate in enumerate(self.returned, start=1):
            if any(answers(candidate, key) for key in self.expected):
                return position
        return None


@dataclass(frozen=True)
class Interval:
    low: float
    high: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high

    def __str__(self) -> str:
        return f"{self.low:.2f} to {self.high:.2f}"


@dataclass(frozen=True)
class Score:
    questions: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    interval: Interval
    """For recall@5, which is the number CI gates on."""

    misses: tuple[str, ...]


def recall_at(outcomes: Sequence[Outcome], k: int) -> float:
    if not outcomes:
        return 0.0
    return sum(outcome.hit_at(k) for outcome in outcomes) / len(outcomes)


def mean_reciprocal_rank(outcomes: Sequence[Outcome]) -> float:
    if not outcomes:
        return 0.0
    total = sum(1 / outcome.first_hit for outcome in outcomes if outcome.first_hit)
    return total / len(outcomes)


def bootstrap_interval(
    outcomes: Sequence[Outcome], k: int = 5, resamples: int = RESAMPLES, seed: int = 0
) -> Interval:
    """How much the score would move on a different sample of questions.

    Resampling the questions with replacement, many times, shows the range the
    measurement supports. The seed is fixed so that CI comparing two runs is
    comparing scores, not random draws.
    """
    if not outcomes:
        return Interval(0.0, 0.0)

    rng = random.Random(seed)
    hits = [outcome.hit_at(k) for outcome in outcomes]
    size = len(hits)
    draws = sorted(sum(rng.choice(hits) for _ in range(size)) / size for _ in range(resamples))

    tail = (1 - CONFIDENCE) / 2
    low = draws[int(tail * resamples)]
    high = draws[min(int((1 - tail) * resamples), resamples - 1)]
    return Interval(low=low, high=high)


def score(outcomes: Sequence[Outcome]) -> Score:
    return Score(
        questions=len(outcomes),
        recall_at_5=recall_at(outcomes, 5),
        recall_at_10=recall_at(outcomes, 10),
        mrr=mean_reciprocal_rank(outcomes),
        interval=bootstrap_interval(outcomes, k=5),
        misses=tuple(outcome.question_id for outcome in outcomes if not outcome.hit_at(5)),
    )
