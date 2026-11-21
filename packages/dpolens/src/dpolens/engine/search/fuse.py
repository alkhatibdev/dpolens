"""Combining two ranked lists into one.

Keyword and meaning search score on different scales, so their numbers cannot
simply be added. Three rules are implemented here, and the evals choose between
them.

Convex combination rescales each list to 0 to 1 and blends them at a fixed weight.
Standardised fusion standardises each list within the question instead, so that a
clause counts for how far it stands above the rest of its list, where rescaling
gives the best of a list a full score however weak it is. Reciprocal rank fusion
ignores the scores and uses only positions.

A weight is fitted only where the practice questions can carry it: one number,
chosen by cross-validation, on a curve that is flat around it. evals/retrieval.md
shows the measurements.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dpolens.engine.search.keyword import Candidate

DEFAULT_K = 10
DEFAULT_ALPHA = 0.5
DEFAULT_KEYWORD_WEIGHT = 0.3
RULES = {"rrf": DEFAULT_K, "convex": DEFAULT_ALPHA, "standardised": DEFAULT_KEYWORD_WEIGHT}


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
        """Read 'standardised:0.3', 'convex:0.5' or 'rrf:10', which is how the evals name a run."""
        rule, _, parameter = value.partition(":")
        if rule not in RULES:
            raise ValueError(f"unknown fusion rule {rule!r}: expected standardised, convex or rrf")
        return cls(rule=rule, parameter=float(parameter) if parameter else RULES[rule])


DEFAULT_FUSION = Fusion(rule="convex", parameter=DEFAULT_ALPHA)
"""The rule search uses unless told otherwise, and the one the published score
measures. On the held-out questions it finds the right clause as often as
reciprocal rank fusion and ranks it higher."""


def fuse(lists: Mapping[str, Sequence[Candidate]], fusion: Fusion = DEFAULT_FUSION) -> list[Fused]:
    if fusion.rule == "rrf":
        return reciprocal_rank(lists, k=int(fusion.parameter))
    if fusion.rule == "standardised":
        return standardised(lists, keyword_weight=fusion.parameter)
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


def standardised(
    lists: Mapping[str, Sequence[Candidate]], keyword_weight: float = DEFAULT_KEYWORD_WEIGHT
) -> list[Fused]:
    """Standardise each list within the question, then add them, the first at `keyword_weight`.

    A clause one list did not find takes that list's lowest score: the least it could have had
    there, and no less, since a list of a hundred says nothing of what is below it.
    """
    if len(lists) != 2:
        raise ValueError("standardised fusion is defined here for exactly two retrievers")

    weights = [keyword_weight, 1 - keyword_weight]
    standard: list[dict[str, float]] = []
    ranks: dict[str, dict[str, int]] = {}
    langs: dict[str, str] = {}
    for retriever, candidates in lists.items():
        values = _to_standard([candidate.score for candidate in candidates])
        standard.append(
            {candidate.key: value for candidate, value in zip(candidates, values, strict=True)}
        )
        for candidate in candidates:
            ranks.setdefault(candidate.key, {})[retriever] = candidate.rank
            langs.setdefault(candidate.key, candidate.lang)

    floors = [min(values.values(), default=0.0) for values in standard]
    scores = {
        key: sum(
            weight * values.get(key, floor)
            for weight, values, floor in zip(weights, standard, floors, strict=True)
        )
        for key in ranks
    }
    return _ordered(scores, ranks, langs)


def standardised_scores(candidates: Sequence[Candidate]) -> list[float]:
    """How far each candidate's score stands above or below the rest of its list, in spreads."""
    return _to_standard([candidate.score for candidate in candidates])


def _to_standard(scores: Sequence[float]) -> list[float]:
    if not scores:
        return []
    mean = statistics.fmean(scores)
    spread = statistics.pstdev(scores)
    if spread == 0:
        # Every candidate scored the same, so none stands above another.
        return [0.0 for _ in scores]
    return [(score - mean) / spread for score in scores]


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
