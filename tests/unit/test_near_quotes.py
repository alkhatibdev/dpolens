"""A question that nearly quotes a clause gets that clause first.

Keyword search counts for less than meaning, which suits a question in everyday words. A question
that repeats a clause's own words is asking for that clause. Which clause a question quotes is
arithmetic on how many of its content words each candidate's own words hold.
"""

from __future__ import annotations

from dpolens.engine.search.keyword import QUOTED_SHARE, QUOTED_WORDS, quote_of

KEYS = ["law:a", "law:b", "law:c"]


def test_a_clause_holding_nearly_every_content_word_is_quoted() -> None:
    assert quote_of(10, {"law:a": 4, "law:b": 9, "law:c": 2}, KEYS) == "law:b"


def test_a_clause_holding_most_but_not_nearly_all_is_not() -> None:
    assert quote_of(10, {"law:a": 8, "law:b": 7}, KEYS) is None


def test_a_short_question_quotes_nothing_however_much_a_clause_holds() -> None:
    """Four content words are held by many clauses that do not answer them."""
    assert QUOTED_WORDS == 5
    assert quote_of(4, {"law:a": 4}, KEYS) is None
    assert quote_of(5, {"law:a": 5}, KEYS) == "law:a"


def test_of_several_the_one_holding_most_then_the_better_keyword_place() -> None:
    assert quote_of(10, {"law:a": 9, "law:b": 10, "law:c": 10}, KEYS) == "law:b"
    assert quote_of(10, {"law:c": 9, "law:a": 9}, KEYS) == "law:a"


def test_the_share_is_nine_in_ten() -> None:
    assert QUOTED_SHARE == 0.9
    assert quote_of(20, {"law:a": 18}, KEYS) == "law:a"
    assert quote_of(20, {"law:a": 17}, KEYS) is None
