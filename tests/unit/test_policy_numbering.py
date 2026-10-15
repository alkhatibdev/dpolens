"""Word's automatic numbers, drawn as Word draws them.

They are not text in the file, and a policy's keys come from them, so each of Word's rules
that changes a number has a case here.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from dpolens.engine.policies.docx import read_docx
from dpolens.engine.policies.numbering import Numbering, drawn

FIXTURES = Path(__file__).parents[1] / "fixtures" / "policies"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@pytest.fixture(scope="module")
def labels() -> list[str]:
    found = read_docx((FIXTURES / "numbering-formats.docx").read_bytes())
    return [p.number.label for p in found.paragraphs() if p.number is not None]


def test_each_level_draws_in_its_own_format(labels: list[str]) -> None:
    assert labels[:3] == ["1.", "(a)", "(i)"]


def test_a_level_starts_again_after_a_higher_one(labels: list[str]) -> None:
    assert labels[3:5] == ["2.", "(a)"]


def test_arabic_letters_and_digits(labels: list[str]) -> None:
    assert labels[5:8] == ["أ-", "ب-", "١."]


def test_legal_numbering_shows_every_level_as_a_digit(labels: list[str]) -> None:
    """The top level is drawn "I." on its own, and as "1" inside a legal number."""
    assert labels[8:10] == ["I.", "1.1"]


def test_a_list_asked_to_start_again_does_so(labels: list[str]) -> None:
    assert labels[10] == "5."


def test_a_level_that_never_restarts_carries_on(labels: list[str]) -> None:
    assert labels[11:14] == ["(1)", "1.", "(2)"]


def test_lists_sharing_a_definition_share_its_count(labels: list[str]) -> None:
    """A definition that stands for a numbering style counts on from the lists that use it."""
    assert labels[14] == "6."


@pytest.mark.parametrize(
    ("value", "form", "expected"),
    [
        (27, "lowerLetter", "aa"),
        (4, "upperRoman", "IV"),
        (3, "ordinal", "3rd"),
        (12, "ordinal", "12th"),
        (2, "cardinalText", "Two"),
        (3, "arabicAlpha", "ت"),
        (3, "arabicAbjad", "ج"),
        (5, "decimalZero", "05"),
        (12, "hindiNumbers", "١٢"),
    ],
)
def test_formats(value: int, form: str, expected: str) -> None:
    assert drawn(value, form) == expected


def test_a_format_it_cannot_draw_is_shown_as_a_number_and_said() -> None:
    definitions = ElementTree.fromstring(
        f'<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0">'
        '<w:numFmt w:val="chicago"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num></w:numbering>'
    )
    numbering = Numbering(definitions, lambda style: None)

    number = numbering.number("1", 0)

    assert number is not None
    assert number.label == "1."
    assert numbering.undrawn == {"chicago"}
