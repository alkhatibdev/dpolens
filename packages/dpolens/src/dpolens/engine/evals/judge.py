"""Judging whether a change to search made it better.

Two runs over the same questions are compared question by question. What counts is how far
up the right clause sits, not only whether it reached the top five: a clause that climbs
from ninth to sixth has moved, and a count of hits at five does not see it.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

CHANCE = 0.05
"""A gain counts when chance alone would give one as large less often than this."""

SHUFFLES = 10_000
"""How many times each topic's change is given a random sign."""

DEPTH = 10
"""How many results a question is scored over, which is what an eval run returns."""

HIT = 5


class Unpaired(Exception):
    """The two runs did not ask the same questions, so there is nothing to compare."""


@dataclass(frozen=True)
class Placed:
    """Where the first clause that answers one question came, in one run."""

    pack: str
    question_set: str
    question_id: str
    topic: str
    place: int | None
    """Counting from one, or None when no returned clause answers."""
    rules: bool = False
    """Whether the run returned whole rules, which counts a result by what it shows."""

    @property
    def score(self) -> float:
        """One for first place, a half for second, down to a tenth, and nothing below."""
        return 1.0 / self.place if self.place is not None and self.place <= DEPTH else 0.0

    @property
    def hit(self) -> bool:
        return self.place is not None and self.place <= HIT


@dataclass(frozen=True)
class SetChange:
    """One question set, before and after."""

    pack: str
    question_set: str
    questions: int
    hits_before: int
    hits_after: int
    score_before: float
    score_after: float
    chance_of_loss: float
    """How often chance alone gives this set a loss as large as the one it shows."""
    worse: bool


@dataclass(frozen=True)
class Judgement:
    questions: int
    topics: int
    hits_before: int
    hits_after: int
    score_before: float
    score_after: float
    topics_found: int
    topics_lost: int
    chance: float
    """How often chance alone gives a gain as large as the one measured."""
    sets: tuple[SetChange, ...]

    @property
    def kept(self) -> bool:
        return self.chance < CHANCE and not any(change.worse for change in self.sets)


def topic_of(question_id: str, named: str | None = None) -> str:
    """The topic a question asks about: the one it names, or its id. A set that asks a topic
    twice, formally and the way people type in chat, gives the second question the first's id
    with -chat after it."""
    return named or question_id.removesuffix("-chat")


def placed_in(record: Mapping[str, Any]) -> list[Placed]:
    """Every question of an outcomes file, as `dpolens evals run --outcomes` writes it."""
    rules = "rules" in str(record.get("configuration", "")).split("+")[1:]
    return [
        Placed(
            pack=str(record["pack"]),
            question_set=str(asked["question_set"]),
            question_id=str(question["id"]),
            topic=str(question["topic"]),
            place=question["place"],
            rules=rules,
        )
        for asked in record["sets"]
        for question in asked["questions"]
    ]


def chance_of_gain(changes: Sequence[float], seed: int = 0) -> float:
    """How often giving each change a random sign adds up to at least what they add up to.

    If a change to search did nothing, a topic would be as likely to move down as up, so
    each topic's change could as well have had the other sign. The seed is fixed, so judging
    the same two runs twice gives the same answer.
    """
    measured = sum(changes)
    if measured <= 0:
        return 1.0
    chooser = random.Random(seed)
    at_least = sum(
        sum(change if chooser.random() < 0.5 else -change for change in changes) >= measured - 1e-12
        for _ in range(SHUFFLES)
    )
    return (at_least + 1) / (SHUFFLES + 1)


def judge(before: Sequence[Placed], after: Sequence[Placed]) -> Judgement:
    """Compare two runs over the same questions.

    A topic asked more than once, in another language or as chat, is one topic: its
    questions move together, so their changes are added before any sign is shuffled. The
    change is kept when its gain is more than chance gives and no set is worse. A set is
    worse when its score falls by more than chance explains, by the same test on that set
    alone, with the chance allowed shared across the sets so that looking at many does not
    find a loss in one by accident.
    """
    if len({placed.rules for placed in [*before, *after]}) > 1:
        raise Unpaired(
            "one run returned whole rules (+rules) and the other clauses, so a place means "
            "something else in each: a change of what a result is is restated, not judged"
        )
    earlier = {(placed.pack, placed.question_set, placed.question_id): placed for placed in before}
    later = {(placed.pack, placed.question_set, placed.question_id): placed for placed in after}
    if len(earlier) != len(before) or len(later) != len(after):
        raise Unpaired("a run holds a question twice, as two files for one law would")
    if earlier.keys() != later.keys():
        unmatched = sorted(earlier.keys() ^ later.keys())
        named = ", ".join("/".join(key) for key in unmatched[:3])
        raise Unpaired(
            f"the two runs do not ask the same questions: {len(unmatched)} in one run only, "
            f"such as {named}"
        )
    if not earlier:
        raise Unpaired("the runs hold no questions")

    by_topic: dict[tuple[str, str], float] = defaultdict(float)
    hits_by_topic: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    by_set: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for key, was in earlier.items():
        now = later[key]
        change = now.score - was.score
        by_topic[(was.pack, was.topic)] += change
        by_set[(was.pack, was.question_set)][was.topic] += change
        hits_by_topic[(was.pack, was.topic)][0] += was.hit
        hits_by_topic[(was.pack, was.topic)][1] += now.hit

    sets = []
    for (pack, question_set), changes in by_set.items():
        was_asked = [
            placed
            for placed in before
            if (placed.pack, placed.question_set) == (pack, question_set)
        ]
        now_asked = [later[(p.pack, p.question_set, p.question_id)] for p in was_asked]
        score_before = sum(placed.score for placed in was_asked) / len(was_asked)
        score_after = sum(placed.score for placed in now_asked) / len(now_asked)
        chance_of_loss = chance_of_gain([-change for change in changes.values()])
        sets.append(
            SetChange(
                pack=pack,
                question_set=question_set,
                questions=len(was_asked),
                hits_before=sum(placed.hit for placed in was_asked),
                hits_after=sum(placed.hit for placed in now_asked),
                score_before=score_before,
                score_after=score_after,
                chance_of_loss=chance_of_loss,
                worse=score_after < score_before and chance_of_loss < CHANCE / len(by_set),
            )
        )

    return Judgement(
        questions=len(earlier),
        topics=len(by_topic),
        hits_before=sum(placed.hit for placed in earlier.values()),
        hits_after=sum(placed.hit for placed in later.values()),
        score_before=sum(placed.score for placed in earlier.values()) / len(earlier),
        score_after=sum(placed.score for placed in later.values()) / len(later),
        topics_found=sum(1 for was, now in hits_by_topic.values() if now > was),
        topics_lost=sum(1 for was, now in hits_by_topic.values() if now < was),
        chance=chance_of_gain(list(by_topic.values())),
        sets=tuple(sets),
    )
