"""Search questions, without a database: the words they were written for, and the one way
they may change what search returns."""

from __future__ import annotations

import pytest

from dpolens.engine.evals import check_configuration
from dpolens.engine.search.fuse import DEFAULT_FUSION, fuse
from dpolens.engine.search.keyword import Candidate
from dpolens.engine.search.questions import fingerprint, with_questions


def listed(*found: tuple[str, float]) -> list[Candidate]:
    return [
        Candidate(key=key, lang="en", score=score, rank=rank)
        for rank, (key, score) in enumerate(found, start=1)
    ]


LISTS = {
    "keyword": listed(("law:a", 9.0), ("law:c", 8.5), ("law:b", 8.0), ("policy:x", 6.0)),
    "meaning": listed(
        ("law:b", 0.84), ("policy:x", 0.83), ("law:a", 0.82), ("law:c", 0.80), ("law:d", 0.70)
    ),
}


def test_a_fingerprint_reads_the_words_not_how_they_were_spaced() -> None:
    assert fingerprint({"en": "Personal data  shall\nbe kept"}) == fingerprint(
        {"en": "Personal data shall be kept"}
    )


def test_a_fingerprint_changes_with_the_words_in_any_language() -> None:
    both = fingerprint({"ar": "تحفظ البيانات", "en": "Data shall be kept"})

    assert both != fingerprint({"ar": "تحفظ البيانات", "en": "Data shall be erased"})
    assert both != fingerprint({"en": "Data shall be kept"})


def test_a_close_question_moves_its_clause_into_the_best_place_a_carded_clause_held() -> None:
    fused = fuse(LISTS, DEFAULT_FUSION)

    reordered = with_questions(LISTS, fused, {"law:a": 0.1, "law:c": 0.99}, DEFAULT_FUSION)

    places = [item.key for item in fused]
    assert places.index("law:a") < places.index("law:c")
    moved = [item.key for item in reordered]
    assert moved.index("law:c") < moved.index("law:a")


def test_a_clause_without_questions_keeps_its_place_and_every_place_its_score() -> None:
    fused = fuse(LISTS, DEFAULT_FUSION)

    reordered = with_questions(LISTS, fused, {"law:a": 0.1, "law:c": 0.99}, DEFAULT_FUSION)

    for before, after in zip(fused, reordered, strict=True):
        assert after.score == before.score
        if before.key not in ("law:a", "law:c"):
            assert after == before


def test_a_question_cannot_bring_in_a_clause_search_did_not_find() -> None:
    fused = fuse(LISTS, DEFAULT_FUSION)

    reordered = with_questions(LISTS, fused, {"law:elsewhere": 1.0}, DEFAULT_FUSION)

    assert [item.key for item in reordered] == [item.key for item in fused]


@pytest.mark.parametrize("configuration", ["keyword+questions", "meaning+questions"])
def test_a_single_retriever_has_no_use_for_the_questions(configuration: str) -> None:
    with pytest.raises(ValueError, match="nothing reads: \\+questions"):
        check_configuration(configuration)


def test_a_fusion_rule_takes_the_questions() -> None:
    check_configuration("convex:0.5+normative+questions")
