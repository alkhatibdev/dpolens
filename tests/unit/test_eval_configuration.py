"""Naming what an eval run scores.

A configuration that cannot run as written would score something else and report
it under the name that was asked for, so it is refused before anything runs.
"""

from __future__ import annotations

import re

import pytest

from dpolens.engine.evals import check_configuration


@pytest.mark.parametrize(
    "configuration",
    [
        "keyword",
        "meaning+normative",
        "rrf:10",
        "convex:0.5+normative",
        "convex:0.5+normative+light",
        "keyword+normative+snowball",
        "convex:0.5+folded-snowball",
    ],
)
def test_a_configuration_that_runs_as_written_is_accepted(configuration: str) -> None:
    check_configuration(configuration)


@pytest.mark.parametrize(
    ("configuration", "named"),
    [
        # A typo used to run the default under the name of the index asked for.
        ("convex:0.5+normative+ligth", "+ligth"),
        ("keyword+Normative", "+Normative"),
        ("meaning+rerankten", "+rerankten"),
    ],
)
def test_a_modifier_nothing_reads_is_refused(configuration: str, named: str) -> None:
    with pytest.raises(ValueError, match=re.escape(f"nothing reads: {named}")):
        check_configuration(configuration)


@pytest.mark.parametrize(
    "configuration",
    ["convex:0.5+light+snowball", "keyword+rerank10+rerank25"],
)
def test_two_of_a_kind_are_refused_since_which_one_wins_would_vary(configuration: str) -> None:
    with pytest.raises(ValueError, match="more than one"):
        check_configuration(configuration)


def test_reranking_needs_a_reranker_to_do_it() -> None:
    with pytest.raises(ValueError, match="no reranker was given"):
        check_configuration("convex:0.5+rerank25")

    check_configuration("convex:0.5+rerank25", reranker=object())  # type: ignore[arg-type]


def test_an_unknown_fusion_rule_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown fusion rule"):
        check_configuration("bm25+normative")
