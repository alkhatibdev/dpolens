"""Combining two ranked lists.

These are arithmetic, so they are tested on hand-built lists rather than on a
corpus: what the rules do to real questions is the evals' job.
"""

from __future__ import annotations

import pytest

from dpolens.engine.search.fuse import Fusion, convex, fuse, reciprocal_rank
from dpolens.engine.search.keyword import Candidate


def candidates(*pairs: tuple[str, float]) -> list[Candidate]:
    return [
        Candidate(key=key, lang="en", score=score, rank=position)
        for position, (key, score) in enumerate(pairs, start=1)
    ]


def test_a_clause_both_retrievers_found_outranks_one_they_split() -> None:
    lists = {
        "keyword": candidates(("a", 9.0), ("b", 8.0)),
        "meaning": candidates(("b", 0.9), ("c", 0.8)),
    }

    fused = reciprocal_rank(lists, k=10)

    assert fused[0].key == "b"
    assert fused[0].ranks == {"keyword": 2, "meaning": 1}


def test_reciprocal_rank_uses_positions_not_scores() -> None:
    """One list with wild scores must not overwhelm the other."""
    modest = {"keyword": candidates(("a", 1.0)), "meaning": candidates(("b", 0.9))}
    wild = {"keyword": candidates(("a", 10_000.0)), "meaning": candidates(("b", 0.9))}

    assert [item.score for item in reciprocal_rank(modest)] == [
        item.score for item in reciprocal_rank(wild)
    ]


def test_k_decides_how_much_the_top_position_is_worth() -> None:
    lists = {"keyword": candidates(("a", 1.0), ("b", 0.5)), "meaning": candidates(("b", 0.9))}

    small_k = reciprocal_rank(lists, k=10)
    large_k = reciprocal_rank(lists, k=60)

    # With a small k, being first somewhere matters more, so the gap widens.
    assert small_k[0].score - small_k[1].score > large_k[0].score - large_k[1].score


def test_convex_combination_normalises_each_list() -> None:
    lists = {
        "keyword": candidates(("a", 100.0), ("b", 0.0)),
        "meaning": candidates(("b", 0.9), ("a", 0.1)),
    }

    fused = {item.key: item.score for item in convex(lists, alpha=0.5)}

    # a is best on keyword, b is best on meaning, so at equal weight they tie.
    assert fused["a"] == pytest.approx(fused["b"])


def test_convex_handles_a_list_where_everything_scored_the_same() -> None:
    lists = {
        "keyword": candidates(("a", 1.0), ("b", 1.0)),
        "meaning": candidates(("b", 0.5), ("a", 0.4)),
    }

    fused = convex(lists, alpha=0.5)

    assert fused[0].key == "b"


def test_results_are_ordered_and_stable() -> None:
    lists = {"keyword": candidates(("b", 1.0), ("a", 1.0)), "meaning": candidates(("a", 1.0))}

    fused = reciprocal_rank(lists)
    scores = [item.score for item in fused]

    assert scores == sorted(scores, reverse=True)
    assert [item.key for item in reciprocal_rank(lists)] == [item.key for item in fused]


def test_a_fusion_rule_is_named_so_a_published_score_can_state_it() -> None:
    assert Fusion.parse("rrf:60").name == "rrf:60"
    assert Fusion.parse("convex:0.5").name == "convex:0.5"
    assert Fusion.parse("rrf").name == "rrf:10"

    with pytest.raises(ValueError, match="unknown fusion rule"):
        Fusion.parse("magic:1")


def test_fuse_dispatches_on_the_rule() -> None:
    lists = {"keyword": candidates(("a", 1.0)), "meaning": candidates(("b", 1.0))}

    assert [item.key for item in fuse(lists, Fusion.parse("rrf:10"))] == ["a", "b"]
    assert len(fuse(lists, Fusion.parse("convex:0.5"))) == 2


def test_convex_refuses_a_shape_it_is_not_defined_for() -> None:
    with pytest.raises(ValueError, match="exactly two retrievers"):
        convex({"keyword": candidates(("a", 1.0))}, alpha=0.5)
