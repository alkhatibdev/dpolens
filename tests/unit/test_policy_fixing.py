"""Fixing what was read: each tool reshapes the tree, keys follow, and no word changes."""

from __future__ import annotations

import pytest

from dpolens.engine.policies.fixing import (
    CannotFix,
    Part,
    apply,
    boundaries,
    keyed,
    locate,
    possible,
    walk,
)
from dpolens.engine.policies.parse import parse_policy
from dpolens.engine.policies.tree import Clause, Edit, Suggestion

POLICY = b"""# Acceptable use policy

## 1. Purpose

1.1 This policy sets out how Acme's systems may be used.

## 2. Scope

2.1 It applies to everyone with an Acme account.

## Personal use

Occasional personal use is allowed, as long as no customer data is involved.

## 3. Monitoring

3.1 Acme records who opens systems that hold personal data, to detect misuse. 3.2 The records \
are kept for 90 days.

3.3 Records are read only by the security team, and only

when misuse is suspected.
"""


def parts_of(clauses: tuple[Clause, ...]) -> list[Part]:
    return [
        Part(
            kind=clause.kind,
            layer=clause.layer,
            label=clause.label,
            heading=clause.heading,
            lines=clause.text.split("\n") if clause.text else [],
            positions=list(clause.positions),
            children=parts_of(clause.children),
            key=clause.key,
            lang=clause.lang,
        )
        for clause in clauses
    ]


def tree() -> list[Part]:
    return parts_of(parse_policy(POLICY, "acceptable-use.md", "aup").clauses)


def outline(roots: list[Part]) -> list[str]:
    return [part.key.removeprefix("aup:") for part in walk(roots)]


def fix(roots: list[Part], edit: Edit, key: str, at: int | None = None) -> Part:
    found = locate(roots, f"aup:{key}")
    assert found is not None
    result = apply(roots, edit, found, at)
    keyed("aup", roots)
    return result.after


def test_the_policy_reads_as_expected_before_any_fix() -> None:
    assert outline(tree()) == [
        "1",
        "1.1",
        "2",
        "2.1",
        "personal-use",
        "personal-use:p1",
        "3",
        "3.1",
        "3.3",
        "3:p1",
    ]


def test_split_at_a_sentence_makes_a_number_there_the_second_part_s_key() -> None:
    roots = tree()
    clause = locate(roots, "aup:3.1")
    assert clause is not None
    at = clause.text.index("3.2 The records")

    first = fix(roots, "split", "3.1", at)

    assert outline(roots)[6:9] == ["3", "3.1", "3.2"]
    second = locate(roots, "aup:3.2")
    assert second is not None
    assert first.text == "Acme records who opens systems that hold personal data, to detect misuse."
    assert (second.label, second.text) == ("3.2", "The records are kept for 90 days.")
    assert (first.layer, first.fixed, second.layer, second.fixed) == (
        "reviewer",
        "split",
        "reviewer",
        "split",
    )
    # Split inside one paragraph, both parts hold it.
    assert first.positions == second.positions


def test_split_is_only_where_a_sentence_or_a_paragraph_begins() -> None:
    roots = tree()
    clause = locate(roots, "aup:3.1")
    assert clause is not None

    with pytest.raises(CannotFix, match="none begins there"):
        apply(roots, "split", clause, clause.text.index("records"))


def test_a_clause_with_clauses_under_it_is_not_split() -> None:
    roots = tree()
    parent = Part("paragraph", "numbering", "9.", None, ["One. Two."], [1])
    parent.children.append(Part("paragraph", "numbering", "9.1", None, ["Three."], [2]))
    roots.append(parent)

    with pytest.raises(CannotFix, match="Move them out a level first"):
        apply(roots, "split", parent, 5)


def test_merge_with_the_one_before_joins_a_rule_cut_in_two() -> None:
    roots = tree()

    merged = fix(roots, "merge", "3:p1")

    assert merged.key == "aup:3.3"
    assert merged.text == (
        "Records are read only by the security team, and only\nwhen misuse is suspected."
    )
    assert (merged.layer, merged.fixed) == ("reviewer", "merged")
    assert "3:p1" not in outline(roots)


def test_merge_keeps_a_merged_clause_s_number_in_its_words() -> None:
    roots = tree()

    merged = fix(roots, "merge", "3.3")

    assert merged.key == "aup:3.1"
    assert merged.text.splitlines()[-1] == (
        "3.3 Records are read only by the security team, and only"
    )


def test_merge_needs_a_clause_before_it_of_the_same_kind() -> None:
    roots = tree()
    text = Part("paragraph", "native_structure", None, None, ["Text."], [51])
    roots.extend([Part("section", "native_structure", None, "Heading", [], [50]), text])

    with pytest.raises(CannotFix, match="no clause before it"):
        fix(roots, "merge", "1")
    with pytest.raises(CannotFix, match="move this one under it instead"):
        apply(roots, "merge", text)


def test_move_under_the_one_before_takes_its_clauses_along() -> None:
    roots = tree()

    moved = fix(roots, "move-under", "personal-use")

    assert moved.key == "aup:2:personal-use"
    assert outline(roots)[2:6] == ["2", "2.1", "2:personal-use", "2:personal-use:p1"]
    assert (moved.layer, moved.fixed) == ("reviewer", "moved-under")


def test_move_out_a_level_brings_what_follows_it_along() -> None:
    roots = tree()

    moved = fix(roots, "move-out", "3.1")

    # 3.3 and the paragraph after it came out with 3.1, in the file's order.
    assert outline(roots)[6:] == ["3", "3.1", "3.3", "p1"]
    assert moved.fixed == "moved-out"
    assert {part.fixed for part in walk(roots) if part.key in ("aup:3.3", "aup:p1")} == {
        "moved-out"
    }


def test_a_heading_moved_out_holds_what_follows_it() -> None:
    roots = tree()
    fix(roots, "move-under", "personal-use")
    fix(roots, "move-under", "3")

    fix(roots, "move-out", "2:personal-use")

    assert outline(roots)[4:] == [
        "personal-use",
        "personal-use:p1",
        "personal-use:3",
        "personal-use:3.1",
        "personal-use:3.3",
        "personal-use:3:p1",
    ]


def test_make_it_text_lets_what_was_under_it_follow_it() -> None:
    roots = tree()

    made = fix(roots, "make-text", "personal-use")

    assert (made.kind, made.heading, made.text) == ("paragraph", None, "Personal use")
    assert outline(roots)[4:6] == ["p1", "p2"]
    assert made.fixed == "made-text"


def test_make_it_a_heading_takes_one_paragraph() -> None:
    roots = tree()
    fix(roots, "make-text", "personal-use")

    made = fix(roots, "make-heading", "p1")

    assert (made.kind, made.heading, made.key) == ("section", "Personal use", "aup:personal-use")
    fix(roots, "merge", "3:p1")
    with pytest.raises(CannotFix, match=r"this clause has 2\. Split it first"):
        fix(roots, "make-heading", "3.3")


def test_the_first_clause_has_nothing_to_move_under_and_the_top_nothing_to_leave() -> None:
    roots = tree()

    with pytest.raises(CannotFix, match="no clause before it to move it under"):
        fix(roots, "move-under", "1")
    with pytest.raises(CannotFix, match="top level already"):
        fix(roots, "move-out", "1")


def test_no_word_changes_whatever_is_fixed() -> None:
    roots = tree()
    before = " ".join(
        " ".join(filter(None, [part.label, part.heading, part.text])) for part in walk(roots)
    ).split()
    clause = locate(roots, "aup:3.1")
    assert clause is not None
    fix(roots, "split", "3.1", clause.text.index("3.2 The"))
    fix(roots, "move-under", "personal-use")
    fix(roots, "make-text", "2:personal-use")
    fix(roots, "merge", "3:p1")

    after = " ".join(
        " ".join(filter(None, [part.label, part.heading, part.text])) for part in walk(roots)
    ).split()
    assert sorted(after) == sorted(before)


def test_boundaries_are_where_sentences_paragraphs_and_listed_numbers_begin() -> None:
    text = "Keep records. Train staff!\nReport breaches; (b) and (c) also: (d) the rest; or not"

    found = boundaries(text)

    assert [text[at : at + 6] for at in found] == ["Train ", "Report", "(b) an", "(d) th"]


def test_possible_tries_an_edit_without_making_it() -> None:
    roots = tree()

    assert possible(roots, "move-under", "aup:personal-use")
    assert not possible(roots, "move-under", "aup:1")
    assert outline(roots)[4] == "personal-use"


def test_a_heading_without_a_number_among_numbered_ones_suggests_moving_it_under() -> None:
    parsed = parse_policy(POLICY, "acceptable-use.md", "aup")

    flagged = [flag for flag in parsed.flags if flag.key == "aup:personal-use"]

    assert [flag.suggestion for flag in flagged] == [Suggestion("move-under")]


def test_a_missing_number_typed_into_the_clause_before_suggests_splitting_there() -> None:
    policy = b"""## 3. Using Acme systems

3.1 Use your own account.

3.2 Lock your screen. 3.3 Clear your desk at the end of the day.

3.4 Never copy customer data to a personal device.
"""
    parsed = parse_policy(policy, "aup.md", "aup")

    gap = next(flag for flag in parsed.flags if flag.kind == "numbering_gap")

    assert gap.detail == "3.4 follows 3.2."
    assert gap.suggestion is not None
    assert (gap.suggestion.edit, gap.suggestion.key, gap.suggestion.label) == (
        "split",
        "aup:3.2",
        "3.3",
    )
    clause = next(clause for clause in parsed.walk() if clause.key == "aup:3.2")
    assert clause.text[gap.suggestion.at or 0 :].startswith("3.3 Clear")
