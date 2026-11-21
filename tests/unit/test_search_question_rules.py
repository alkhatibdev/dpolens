"""Search questions, without a database: the words they were written for, and how a law's
questions join what its clauses' own words found."""

from __future__ import annotations

import pytest

from dpolens.engine.evals import check_configuration
from dpolens.engine.search.keyword import Candidate
from dpolens.engine.search.questions import fingerprint, with_questions


def listed(*found: tuple[str, float]) -> list[Candidate]:
    return [
        Candidate(key=key, lang="en", score=score, rank=rank)
        for rank, (key, score) in enumerate(found, start=1)
    ]


# A clause's own words score lower than questions do, since a question resembles a question
# more than legal text. law:a stands far above the rest of its list; law:e only a little.
MEANING = listed(("law:a", 0.90), ("law:b", 0.80), ("law:c", 0.79), ("law:d", 0.78))
ASKED = listed(("law:e", 0.95), ("law:f", 0.94), ("law:b", 0.93), ("law:g", 0.92))


def test_a_fingerprint_reads_the_words_not_how_they_were_spaced() -> None:
    assert fingerprint({"en": "Personal data  shall\nbe kept"}) == fingerprint(
        {"en": "Personal data shall be kept"}
    )


def test_a_fingerprint_changes_with_the_words_in_any_language() -> None:
    both = fingerprint({"ar": "تحفظ البيانات", "en": "Data shall be kept"})

    assert both != fingerprint({"ar": "تحفظ البيانات", "en": "Data shall be erased"})
    assert both != fingerprint({"en": "Data shall be kept"})


def test_a_question_brings_in_a_clause_its_own_words_did_not() -> None:
    joined = [candidate.key for candidate in with_questions(MEANING, ASKED)]

    assert {"law:e", "law:f", "law:g"} <= set(joined)


def test_each_list_counts_for_how_far_a_clause_stands_above_the_rest_of_it() -> None:
    """Compared raw, every question would outrank every clause's own words."""
    joined = [candidate.key for candidate in with_questions(MEANING, ASKED)]

    assert joined.index("law:a") < joined.index("law:e")


def test_a_clause_found_both_ways_counts_once_at_the_better() -> None:
    joined = with_questions(MEANING, ASKED)
    keys = [candidate.key for candidate in joined]

    assert keys.count("law:b") == 1
    assert [candidate.rank for candidate in joined] == list(range(1, len(joined) + 1))


def test_without_questions_the_meaning_list_is_left_as_it_is() -> None:
    assert with_questions(MEANING, []) == MEANING


@pytest.mark.parametrize("configuration", ["keyword+questions", "meaning+questions"])
def test_a_single_retriever_has_no_use_for_the_questions(configuration: str) -> None:
    with pytest.raises(ValueError, match="nothing reads: \\+questions"):
        check_configuration(configuration)


@pytest.mark.parametrize("swapped", ["light", "snowball"])
def test_with_the_questions_the_law_s_own_arabic_index_goes_unread(swapped: str) -> None:
    with pytest.raises(ValueError, match=f"nothing reads: \\+{swapped}"):
        check_configuration(f"convex:0.5+normative+questions+{swapped}")


@pytest.mark.parametrize(
    "configuration",
    [
        "convex:0.5+normative+questions",
        "standardised:0.3+normative+questions",
        "standardised:0.3+normative+questions+folded-snowball",
    ],
)
def test_a_fusion_rule_takes_the_questions(configuration: str) -> None:
    check_configuration(configuration)
