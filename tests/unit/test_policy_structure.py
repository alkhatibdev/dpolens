"""The layers, from a file's paragraphs to a tree of clauses with keys.

Each test file reproduces something found in real policies, and each test says what a
reviewer should see: where every clause sits, which layer decided it, what was set aside, and
what was flagged instead of guessed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dpolens.engine.policies.parse import parse_policy
from dpolens.engine.policies.tree import Clause, ParsedPolicy

FIXTURES = Path(__file__).parents[1] / "fixtures" / "policies"
EVERY_FILE = sorted(path.name for path in FIXTURES.iterdir() if path.suffix in (".docx", ".md"))


def parse(name: str) -> ParsedPolicy:
    return parse_policy((FIXTURES / name).read_bytes(), name, "x")


def keys(policy: ParsedPolicy) -> list[str]:
    return [clause.key.removeprefix("x:") for clause in policy.walk()]


def clause(policy: ParsedPolicy, key: str) -> Clause:
    return next(found for found in policy.walk() if found.key == f"x:{key}")


def flagged(policy: ParsedPolicy) -> list[tuple[str, str | None]]:
    return [(flag.kind, flag.key and flag.key.removeprefix("x:")) for flag in policy.flags]


@pytest.mark.parametrize("name", EVERY_FILE)
def test_every_character_lands_in_one_clause_or_is_set_aside(name: str) -> None:
    """Coverage, the check every parse runs: nothing dropped, nothing counted twice."""
    policy = parse(name)

    assert policy.coverage.complete
    assert not [flag for flag in policy.flags if flag.kind == "coverage_gap"]


@pytest.mark.parametrize("name", EVERY_FILE)
def test_every_key_names_one_clause(name: str) -> None:
    found = keys(parse(name))

    assert len(found) == len(set(found))


def test_heading_styles_give_the_tree_and_the_title() -> None:
    policy = parse("heading-styles.docx")

    assert policy.title == "Data Protection Policy"
    assert keys(policy) == [
        "purpose-of-the-policy",
        "purpose-of-the-policy:p1",
        "purpose-of-the-policy:p2",
        "individuals-rights",
        "individuals-rights:p1",
        "individuals-rights:p2",
        "data-breaches",
        "data-breaches:p1",
    ]
    assert [block.reason for block in policy.set_aside] == ["front matter", "title"]


def test_bullets_stay_with_the_line_that_leads_into_them() -> None:
    lead_in = clause(parse("heading-styles.docx"), "individuals-rights:p1")

    assert lead_in.text == (
        "The law gives individuals these rights:\n"
        "• the right to be informed\n"
        "• the right of access\n"
        "• the right to erasure"
    )


def test_a_sentence_styled_as_a_heading_is_text_and_flagged() -> None:
    policy = parse("heading-styles.docx")

    assert clause(policy, "individuals-rights:p2").kind == "paragraph"
    assert flagged(policy) == [("low_confidence_boundary", "individuals-rights:p2")]


def test_automatic_numbers_give_the_tree_and_the_keys() -> None:
    policy = parse("automatic-numbering.docx")

    assert keys(policy) == ["1", "1.1", "2", "2.1", "2.2", "3", "3.1", "3.1.1", "3.1.2"]
    assert {found.layer for found in policy.walk()} == {"native_structure"}
    assert clause(policy, "3.1.1") in clause(policy, "3.1").children


def test_a_typed_contents_page_and_a_repeated_table_are_set_aside() -> None:
    reasons = [block.reason for block in parse("automatic-numbering.docx").set_aside]

    assert reasons == ["title", "contents", "front matter", "repeated table"]


def test_a_list_that_starts_again_inside_a_section_is_keyed_under_it() -> None:
    policy = parse("numbered-headings.docx")

    assert keys(policy)[:9] == ["1", "1:p1", "2", "2:p1", "2:1", "2:2", "2:3", "3", "3:p1"]


def test_an_unnumbered_heading_among_numbered_ones_is_flagged() -> None:
    policy = parse("numbered-headings.docx")

    assert flagged(policy) == [("low_confidence_boundary", "paper-storage")]


def test_a_schedule_table_becomes_a_clause_for_each_row() -> None:
    policy = parse("numbered-headings.docx")
    table = clause(policy, "4:document-minimum-retention-period-reason")

    assert table.heading == "DOCUMENT · MINIMUM RETENTION PERIOD · REASON"
    assert [(row.heading, row.text) for row in table.children] == [
        ("Staff records", "6 years\nEmployment law"),
        ("Minutes", "Indefinitely\nArchive"),
    ]


def test_without_heading_styles_bold_and_typed_numbers_give_the_tree() -> None:
    policy = parse("bold-headings.docx")

    assert keys(policy) == [
        "1",
        "1:p1",
        "2",
        "2:p1",
        "2:1",
        "2:2",
        "3",
        "3.1",
        "3.1:p1",
        "3.2",
        "3.2:p1",
        "4",
        "4:who-what",
        "4:who-what:all-staff",
        "4:who-what:line-managers",
    ]
    assert clause(policy, "3.1").layer == "numbering"
    assert clause(policy, "2:1").kind == "paragraph"


def test_headings_with_typed_numbers_take_their_keys_from_the_numbers() -> None:
    policy = parse("typed-numbers.docx")

    assert keys(policy) == [
        "1",
        "1:p1",
        "2",
        "2.1",
        "2.1:p1",
        "2.2",
        "2.2:p1",
        "3",
        "3:term-definition",
        "3:term-definition:personal-data",
        "3:term-definition:processing",
    ]
    assert [block.reason for block in policy.set_aside] == ["front matter"]


def test_arabic_numbers_restart_in_each_section_and_keep_their_hyphens() -> None:
    policy = parse("arabic-sections.docx")

    assert keys(policy) == [
        "الغرض",
        "الغرض:p1",
        "بنود-السياسة",
        "بنود-السياسة:1",
        "بنود-السياسة:1-1",
        "بنود-السياسة:1-2",
        "بنود-السياسة:1-2-1",
        "بنود-السياسة:1-2-2",
        "بنود-السياسة:2",
        "بنود-السياسة:2-1",
        "بنود-السياسة:2-2",
        "الأدوار-والمسؤوليات",
        "الأدوار-والمسؤوليات:1",
        "الأدوار-والمسؤوليات:2",
    ]
    assert {found.lang for found in policy.walk()} == {"ar"}


def test_one_item_lists_with_fixed_labels_are_still_siblings() -> None:
    policy = parse("arabic-sections.docx")

    section = clause(policy, "بنود-السياسة:2")

    assert [child.label for child in section.children] == ["2-1", "2-2"]


def test_requirements_in_tables_nest_under_their_standard() -> None:
    policy = parse("requirements-table.docx")

    assert keys(policy) == [
        "المعايير",
        "المعايير:1",
        "المعايير:1:الهدف",
        "المعايير:1:المخاطر-المحتملة",
        "المعايير:1:الإجراءات-المطلوبة",
        "المعايير:1:الإجراءات-المطلوبة:1-1",
        "المعايير:1:الإجراءات-المطلوبة:1-2",
        "المعايير:2",
        "المعايير:2:الهدف",
        "المعايير:2-1",
    ]
    assert clause(policy, "المعايير:2-1") in clause(policy, "المعايير:2").children


def test_larger_type_marks_headings_where_nothing_else_does() -> None:
    policy = parse("size-headings.docx")

    assert clause(policy, "our-procedures:fair-and-lawful-processing").layer == "typography"
    assert clause(policy, "our-procedures:data-security").layer == "typography"
    # A body style's outline level is not a heading style: its sentences are text, unflagged.
    assert policy.flags == ()


def test_arabic_drafting_numbers_are_read() -> None:
    policy = parse("arabic-patterns.docx")

    assert keys(policy) == [
        "المادة-1",
        "المادة-1:p1",
        "المادة-2",
        "المادة-2:أولا",
        "المادة-2:ثانيا",
        "المادة-3",
        "المادة-3:1",
        "المادة-3:2",
        "المادة-3:2:أ",
        "المادة-3:2:ب",
        "المادة-3:2:ج",
    ]
    assert {found.layer for found in policy.walk() if found.label} == {"numbering"}
    assert policy.flags == ()


def test_each_clause_has_its_own_language() -> None:
    policy = parse("mixed-languages.docx")

    assert [(key, clause(policy, key).lang) for key in keys(policy)] == [
        ("purpose", "en"),
        ("purpose:p1", "en"),
        ("الغرض", "ar"),
        ("الغرض:p1", "ar"),
    ]
