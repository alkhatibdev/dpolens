"""Combining two ranked lists into one.

Keyword and meaning search score on different scales, so their numbers cannot
simply be added. Two rules are implemented here and the evals choose between
them, because the published difference between them is about one point of
recall, which is inside the noise of a fifty-question set.

Reciprocal rank fusion ignores the scores and uses only positions. Convex
combination normalises each list and blends them at a fixed, equal weight. A
fitted weight is deliberately not offered: with thirty held-out questions it
would fit noise and the published number would be dishonest.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dpolens.engine.search.keyword import Candidate

DEFAULT_K = 10
DEFAULT_ALPHA = 0.5


@dataclass(frozen=True)
class Fused:
    """One clause after fusion, with where each retriever put it."""

    key: str
    lang: str
    score: float
    ranks: dict[str, int]

    def found_by(self, retriever: str) -> bool:
        return retriever in self.ranks


@dataclass(frozen=True)
class Fusion:
    """How to combine the lists, named so a published score can state it."""

    rule: str
    parameter: float

    @property
    def name(self) -> str:
        return f"{self.rule}:{self.parameter:g}"

    @classmethod
    def parse(cls, value: str) -> Fusion:
        """Read 'rrf:10' or 'convex:0.5', which is how the evals name a run."""
        rule, _, parameter = value.partition(":")
        if rule not in ("rrf", "convex"):
            raise ValueError(f"unknown fusion rule {rule!r}: expected rrf or convex")
        default = DEFAULT_K if rule == "rrf" else DEFAULT_ALPHA
        return cls(rule=rule, parameter=float(parameter) if parameter else default)


RRF = Fusion(rule="rrf", parameter=DEFAULT_K)
"""The default until the evals say otherwise: it has no weight to overfit."""


def fuse(lists: Mapping[str, Sequence[Candidate]], fusion: Fusion = RRF) -> list[Fused]:
    if fusion.rule == "rrf":
        return reciprocal_rank(lists, k=int(fusion.parameter))
    return convex(lists, alpha=fusion.parameter)


def reciprocal_rank(lists: Mapping[str, Sequence[Candidate]], k: int = DEFAULT_K) -> list[Fused]:
    """Score each clause by 1/(k + rank) in every list that found it."""
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    langs: dict[str, str] = {}

    for retriever, candidates in lists.items():
        for candidate in candidates:
            scores[candidate.key] = scores.get(candidate.key, 0.0) + 1.0 / (k + candidate.rank)
            ranks.setdefault(candidate.key, {})[retriever] = candidate.rank
            langs.setdefault(candidate.key, candidate.lang)

    return _ordered(scores, ranks, langs)


def convex(lists: Mapping[str, Sequence[Candidate]], alpha: float = DEFAULT_ALPHA) -> list[Fused]:
    """Normalise each list to 0 to 1, then blend at a fixed weight.

    With two lists, alpha weights the first and (1 - alpha) the second, so the
    default of 0.5 treats keyword and meaning as equal partners.
    """
    if len(lists) != 2:
        raise ValueError("convex combination is defined here for exactly two retrievers")

    weights = [alpha, 1 - alpha]
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    langs: dict[str, str] = {}

    for weight, (retriever, candidates) in zip(weights, lists.items(), strict=True):
        normalised = _to_unit_range([candidate.score for candidate in candidates])
        for candidate, value in zip(candidates, normalised, strict=True):
            scores[candidate.key] = scores.get(candidate.key, 0.0) + weight * value
            ranks.setdefault(candidate.key, {})[retriever] = candidate.rank
            langs.setdefault(candidate.key, candidate.lang)

    return _ordered(scores, ranks, langs)


def _to_unit_range(scores: Sequence[float]) -> list[float]:
    if not scores:
        return []
    lowest, highest = min(scores), max(scores)
    if highest == lowest:
        # Every candidate scored the same, so position is all that is left.
        return [1.0 for _ in scores]
    span = highest - lowest
    return [(score - lowest) / span for score in scores]


def _ordered(
    scores: dict[str, float], ranks: dict[str, dict[str, int]], langs: dict[str, str]
) -> list[Fused]:
    fused = [
        Fused(key=key, lang=langs[key], score=score, ranks=ranks[key])
        for key, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, item.key))
    return fused
