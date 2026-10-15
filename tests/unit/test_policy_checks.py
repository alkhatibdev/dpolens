"""The checks every parse runs, and the files a parse refuses.

A check is what the parser runs; what it finds is a flag, which the reviewer resolves or
accepts. These build the cases the test files cannot, such as text the reader missed.
"""

from __future__ import annotations

import pytest

from dpolens.engine.policies.blocks import Paragraph, ReadFile, UnreadablePolicy
from dpolens.engine.policies.checks import check_coverage, check_keys, check_numbering
from dpolens.engine.policies.parse import parse_policy
from dpolens.engine.policies.structure import build
from dpolens.engine.policies.tree import Clause


def clause(key: str, label: str | None, children: tuple[Clause, ...] = ()) -> Clause:
    return Clause(
        key=key,
        kind="paragraph",
        layer="native_structure",
        label=label,
        heading=None,
        text="Text.",
        lang="en",
        positions=(),
        children=children,
    )


def test_text_the_reader_missed_is_a_coverage_gap() -> None:
    read = ReadFile(
        format="docx",
        items=(Paragraph(position=0, text="Purpose", heading_level=1),),
        missed=12,
        unread=("someNewElement",),
    )

    coverage, flags = check_coverage(read, build(read))

    assert not coverage.complete
    assert [flag.detail for flag in flags] == [
        "12 characters of text inside someNewElement were not read."
    ]


def test_spacing_is_not_text() -> None:
    read = ReadFile(
        format="docx",
        items=(
            Paragraph(position=0, text="Purpose", heading_level=1),
            Paragraph(position=1, text="   "),
            Paragraph(position=2, text="This policy applies to everyone."),
        ),
    )

    coverage, flags = check_coverage(read, build(read))

    assert coverage.complete
    assert coverage.characters == len("Purpose") + len("Thispolicyappliestoeveryone.")
    assert flags == []


def test_a_gap_in_the_numbering_is_flagged() -> None:
    flags = check_numbering([clause("x:1", "1."), clause("x:2", "2."), clause("x:4", "4.")])

    assert [(flag.key, flag.detail) for flag in flags] == [("x:4", "4. follows 2..")]


def test_a_repeated_number_is_flagged() -> None:
    flags = check_numbering([clause("x:1-1", "1-1"), clause("x:1-1_2", "1-1")])

    assert [flag.detail for flag in flags] == ["1-1 repeats 1-1."]


def test_each_level_is_checked_under_its_own_parent() -> None:
    nested = (clause("x:1:a", "(a)"), clause("x:1:c", "(c)"))

    flags = check_numbering([clause("x:1", "1.", nested), clause("x:2", "2.")])

    assert [flag.key for flag in flags] == ["x:1:c"]


def test_two_clauses_with_one_key_are_flagged() -> None:
    flags = check_keys([clause("x:1", "1."), clause("x:1", "1.")])

    assert [flag.detail for flag in flags] == ["x:1 names 2 clauses."]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("policy.pdf", "PDF files are not read"),
        ("policy.doc", r"older format \(\.doc\)"),
        ("policy.odt", "OpenDocument files are not read"),
        ("policy.xlsx", r"reads Word \(\.docx\) and Markdown \(\.md\)"),
    ],
)
def test_a_format_it_does_not_read_is_refused_with_what_to_do(name: str, message: str) -> None:
    with pytest.raises(UnreadablePolicy, match=message):
        parse_policy(b"anything", name)


def test_a_file_with_no_text_is_refused_rather_than_read_as_empty() -> None:
    """A scanned document holds pictures of its pages; an empty result would look like a
    policy with nothing in it."""
    with pytest.raises(UnreadablePolicy, match="no text to read"):
        parse_policy(b"\n\n   \n", "scanned.md")
