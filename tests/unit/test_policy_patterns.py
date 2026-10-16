"""Numbers written into a policy's text, and how one follows another."""

from __future__ import annotations

import pytest

from dpolens.engine.policies.patterns import Label, follows, parse_label, read_label, segment


def label(text: str) -> Label:
    found = parse_label(text)
    assert found is not None, text
    return found


@pytest.mark.parametrize(
    ("text", "written", "rest"),
    [
        ("4.2 Fair collection", "4.2", "Fair collection"),
        ("4. Introduction", "4.", "Introduction"),
        ("2-2-1 الصيغ الرقمية", "2-2-1", "الصيغ الرقمية"),
        ("(a) the right of access", "(a)", "the right of access"),
        ("iv. the fourth", "iv.", "the fourth"),
        ("Article 5 Lawfulness", "Article 5", "Lawfulness"),
        ("Section 2.1: Purpose", "Section 2.1", "Purpose"),
        ("المادة (5) نطاق السياسة", "المادة (5)", "نطاق السياسة"),
        ("المادة الخامسة: التعاريف", "المادة الخامسة", "التعاريف"),
        ("أولاً: الغرض", "أولاً", "الغرض"),
        ("١- البند الأول", "١-", "البند الأول"),
        ("(أ) البند الأول", "(أ)", "البند الأول"),
        ("Article 5 - Scope", "Article 5", "Scope"),
        ("المادة (5) \u2013 نطاق السياسة", "المادة (5)", "نطاق السياسة"),
    ],
)
def test_reads_a_number_written_into_the_text(text: str, written: str, rest: str) -> None:
    found = read_label(text)

    assert found is not None
    assert (found[0].text, found[1]) == (written, rest)


@pytest.mark.parametrize(
    "text",
    [
        "2018. The year the regulation applied.",
        "e.g. a staff identifier",
        "Mix. the two lists",
        "قسم الموارد البشرية مسؤول عن التدريب.",
        "A data controller decides why data is processed.",
        "أولاً يجب على كل موظف حماية البيانات التي يطلع عليها.",
    ],
)
def test_prose_that_only_looks_numbered_is_not(text: str) -> None:
    assert read_label(text) is None


def test_values_follow_the_numbers_each_script_writes() -> None:
    assert label("المادة (5)").values == (5,)
    assert label("ثانياً:").values == (2,)
    assert label("٣-").values == (3,)
    assert label("ج-").values == (3,)


def test_a_lone_i_is_the_letter_after_h_or_the_first_numeral() -> None:
    assert follows(label("(h)"), label("(i)"))
    assert follows(label("(i)"), label("(ii)"))


def test_the_next_number_at_any_level_follows() -> None:
    assert follows(label("4.2"), label("4.3"))
    assert follows(label("4.5"), label("5.1"))
    assert follows(label("1-1"), label("1-2"))
    assert not follows(label("4.1"), label("4.3"))
    assert not follows(label("2."), label("2."))


def test_arabic_letters_follow_in_either_order() -> None:
    """Abjad order (أ ب ج) and alphabetical order (أ ب ت) are both in use."""
    assert follows(label("ب-"), label("ج-"))
    assert follows(label("ب-"), label("ت-"))


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("(أ)", "أ"),
        ("4.2.", "4.2"),
        ("1-", "1"),
        ("2-2-1", "2-2-1"),
        ("١-", "1"),
        ("Article 5", "article-5"),
        ("المادة (5)", "المادة-5"),
        ("أولاً", "أولا"),
    ],
)
def test_a_number_as_a_key_segment(written: str, expected: str) -> None:
    assert segment(written) == expected
