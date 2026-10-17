"""Reading Markdown policies.

Headings come from the CommonMark parser, so a "#" inside a code block stays text and a line
underlined with dashes is a heading. Policies written in Markdown use the other layers too:
real ones use bold lines as headings and number lists by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dpolens.engine.policies.blocks import UnreadablePolicy
from dpolens.engine.policies.markdown import read_markdown
from dpolens.engine.policies.parse import parse_policy
from dpolens.engine.policies.tree import Clause, ParsedPolicy

FIXTURES = Path(__file__).parents[1] / "fixtures" / "policies"


def parse(name: str) -> ParsedPolicy:
    return parse_policy((FIXTURES / name).read_bytes(), name, "x")


def keys(policy: ParsedPolicy) -> list[str]:
    return [clause.key.removeprefix("x:") for clause in policy.walk()]


def clause(policy: ParsedPolicy, key: str) -> Clause:
    return next(found for found in policy.walk() if found.key == f"x:{key}")


def test_headings_give_the_tree() -> None:
    policy = parse("headings.md")

    assert policy.title == "Acme Privacy Policy"
    assert keys(policy) == [
        "p1",
        "what-we-collect",
        "what-we-collect:p1",
        "what-we-collect:account-data",
        "what-we-collect:account-data:p1",
        "what-we-collect:usage-data",
        "what-we-collect:usage-data:p1",
        "how-long-we-keep-it",
        "how-long-we-keep-it:data-kept-for",
        "how-long-we-keep-it:data-kept-for:account-data",
        "how-long-we-keep-it:data-kept-for:usage-data",
        "your-rights",
        "your-rights:1",
        "your-rights:2",
        "your-rights:p1",
    ]


def test_front_matter_and_a_list_of_links_to_sections_are_set_aside() -> None:
    reasons = [block.reason for block in parse("headings.md").set_aside]

    # The YAML block, the title, the date line, the line that leads into the links, the links.
    assert reasons == ["front matter", "title", "front matter", "front matter", "contents"]


def test_a_line_before_the_policy_is_kept_only_when_it_reads_as_prose() -> None:
    policy = parse_policy(
        """# Acceptable use policy

Owner: Information Security · Version 1.0 · Approved 10 October 2026

Contents: 1 Purpose · 2 Scope · 3 Using Acme systems · 4 Monitoring

This policy sets out how Acme's systems may be used, and by whom, from today.

## 1. Purpose

1.1 Acme's systems are for Acme's work.
""".encode(),
        "aup.md",
        "x",
    )

    assert [(block.reason, block.text[:12]) for block in policy.set_aside] == [
        ("title", "Acceptable u"),
        ("front matter", "Owner: Infor"),
        ("contents", "Contents: 1 "),
    ]
    assert keys(policy) == ["p1", "1", "1.1"]


def test_a_nested_list_stays_with_its_lead_in() -> None:
    lead_in = clause(parse("headings.md"), "what-we-collect:account-data:p1")

    assert lead_in.text == (
        "When you sign up, we ask for:\n"
        "• your name\n"
        "• your email address\n"
        "  • and, if you choose, a second one"
    )


def test_a_list_item_keeps_its_second_paragraph() -> None:
    item = clause(parse("headings.md"), "your-rights:1")

    assert item.text == "You can ask for a copy of your data.\nWe answer within one month."


def test_a_hash_in_a_code_block_is_text() -> None:
    code = clause(parse("headings.md"), "your-rights:p1")

    assert code.text == "# This line is in a code block, so it is text and not a heading."


def test_typed_numbers_in_headings_give_the_keys() -> None:
    assert keys(parse("numbered.md"))[:6] == ["1", "1:p1", "2", "2.1", "2.1:1", "2.1:2"]


def test_a_list_written_one_one_one_counts_as_it_reads() -> None:
    """Markdown draws "1. 1. 1." as 1, 2, 3, and a reader cites the third as 3."""
    policy = parse("numbered.md")

    assert [child.label for child in clause(policy, "2.1").children] == ["1.", "2.", "3."]


def test_bold_lines_and_numbers_typed_by_hand_are_read() -> None:
    policy = parse("numbered.md")

    assert [
        (child.key.removeprefix("x:"), child.layer) for child in clause(policy, "2.2").children
    ] == [
        ("2.2:p1", "native_structure"),
        ("2.2:1", "numbering"),
        ("2.2:2", "numbering"),
        ("2.2:right-to-object", "typography"),
        ("2.2:who-to-contact", "typography"),
    ]


def test_a_list_that_starts_again_after_other_text_is_not_a_slip() -> None:
    policy = parse("numbered.md")

    assert keys(policy)[-6:] == ["3:p1", "3:1", "3:2", "3:p2", "3:1_2", "3:2_2"]
    assert policy.flags == ()


def test_text_that_is_not_utf8_is_refused() -> None:
    with pytest.raises(UnreadablePolicy, match="not UTF-8"):
        read_markdown("# Política\n".encode("latin-1"))
