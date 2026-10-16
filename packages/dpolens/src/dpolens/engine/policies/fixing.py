"""Fixing what was read: the tools a reviewer has, none of which changes a word.

A draft's clauses are a tree, and each tool reshapes it: split a clause where a second rule
begins, merge a clause with the one before it, make a heading text or text a heading, move a
clause under the one before it or out a level. Keys are then given again by the rules a parse
uses, so a clause moved under 3 is keyed as one the parser had put there. Every clause a tool
moved or reshaped is marked as placed by a reviewer, with what was done to it.

Moving a clause out a level brings the clauses after it at its old level along, so the tree
keeps the file's order: a heading holds them, as it would have in the file, and any other clause
is followed by them.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Literal

from dpolens.engine.policies.keys import assign
from dpolens.engine.policies.patterns import read_label
from dpolens.engine.policies.structure import Node
from dpolens.engine.policies.tree import Clause, Edit, Layer

Fixed = Literal["split", "merged", "made-text", "made-heading", "moved-under", "moved-out"]
"""What a reviewer did to a clause, as the clause and a flag the change settled record it."""

DONE: dict[Edit, Fixed] = {
    "split": "split",
    "merge": "merged",
    "make-text": "made-text",
    "make-heading": "made-heading",
    "move-under": "moved-under",
    "move-out": "moved-out",
}

SENTENCE_BREAK = re.compile(r"[.!?؟؛۔][\"'”’)\]]*[ \t ]+(?=\S)")
"""The space after a sentence, where the next one begins."""

LIST_BREAK = re.compile(r"[;:][ \t ]+(?=\S)")
"""The space after a semicolon or colon, a place to split only where a number follows."""

FAMILIES = {"paragraph": "text", "list": "text", "section": "heading", "row": "row"}
"""Which clauses can be merged with which: text with text, a heading with a heading."""


class CannotFix(Exception):
    """The edit cannot be made to that clause, and why, in a sentence."""


@dataclass(eq=False)
class Part:
    """One clause of a draft, as the tools reshape it."""

    kind: str
    layer: Layer
    label: str | None
    heading: str | None
    lines: list[str]
    """Its text, line by line, as `text` joins them."""

    positions: list[int]
    children: list[Part] = field(default_factory=list)
    row: uuid.UUID | None = None
    """The stored clause it is; empty for the second part of a split until it is stored."""

    previous: uuid.UUID | None = None
    """The clause of the version before that it continues."""

    fixed: str | None = None
    change: str | None = None
    """Against the version before: added, modified, moved or unchanged; empty for a first."""

    key: str = ""
    lang: str = ""

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Result:
    """What an edit did: the clause it was made to, and the clauses it changed."""

    subject: Part
    after: Part
    """Where the subject is now: itself, or for a merge the clause it went into."""

    named: Part | None
    """The clause the change names: what it went under or into, or a split's second part."""

    reworded: list[Part]
    """The clauses whose words are not what they were."""

    gone: list[Part]
    marked: list[Part] = field(default_factory=list)
    """Every clause the change moved or reshaped."""


def walk(parts: list[Part]) -> Iterator[Part]:
    for part in parts:
        yield part
        yield from walk(part.children)


def locate(roots: list[Part], key: str) -> Part | None:
    return next((part for part in walk(roots) if part.key == key), None)


def _place(roots: list[Part], part: Part) -> tuple[Part | None, list[Part], int]:
    """The clause's parent, the list it sits in, and where."""

    def search(parent: Part | None, siblings: list[Part]) -> tuple[Part | None, list[Part], int]:
        for index, candidate in enumerate(siblings):
            if candidate is part:
                return parent, siblings, index
            found = search(candidate, candidate.children)
            if found[2] >= 0:
                return found
        return None, [], -1

    found = search(None, roots)
    if found[2] < 0:
        raise ValueError("the clause is not in this tree")
    return found


def boundaries(text: str) -> list[int]:
    """Where a clause's text can be split: where a paragraph or a sentence begins, and where a
    number follows a semicolon or a colon, as in "(a) keep records; (b) train staff"."""
    found: set[int] = set()
    start = 0
    for index, line in enumerate(text.split("\n")):
        if index and line.strip():
            found.add(start + len(line) - len(line.lstrip()))
        for sentence in SENTENCE_BREAK.finditer(line):
            found.add(start + sentence.end())
        for listed in LIST_BREAK.finditer(line):
            numbered = read_label(line[listed.end() :])
            if numbered is not None and not numbered[0].bullet:
                found.add(start + listed.end())
        start += len(line) + 1
    return sorted(at for at in found if 0 < at < len(text))


def opening_number(text: str) -> tuple[str, str] | None:
    """The number a split's second part starts with, and its text after it."""
    found = read_label(text)
    if found is None or found[0].bullet or found[0].style.startswith("word-"):
        # "Section 3 of the Act requires ..." opens a sentence; it numbers nothing.
        return None
    if not found[1].strip():
        return None
    return found[0].text, found[1].strip()


def _mark(fixed: Fixed, *parts: Part) -> list[Part]:
    for part in parts:
        part.layer = "reviewer"
        part.fixed = fixed
    return list(parts)


def _line_places(part: Part, texts: dict[int, str]) -> list[int] | None:
    """The paragraph each line of a clause's text comes from: one each, or as many as the file
    as read shows line breaks in a paragraph."""
    own = part.positions[1:] if part.kind == "section" else part.positions
    if len(own) == len(part.lines):
        return list(own)
    places: list[int] = []
    for position in own:
        text = texts.get(position)
        if text is None:
            return None
        places.extend([position] * (text.count("\n") + 1))
    return places if len(places) == len(part.lines) else None


EDITS: tuple[Edit, ...] = ("split", "merge", "make-text", "make-heading", "move-under", "move-out")


def refusal(
    part: Part, parent: Part | None, siblings: list[Part], index: int, edit: Edit
) -> str | None:
    """Why an edit cannot be made to a clause where it sits, or nothing when it can."""
    before = siblings[index - 1] if index > 0 else None
    match edit:
        case "split":
            if part.kind in ("table", "row"):
                return "A table and its rows are read from the table itself, so neither is split."
            if part.children:
                return (
                    "It has clauses under it. Move them out a level first, then split it, then "
                    "move each one under the part it belongs to."
                )
            if not boundaries(part.text):
                return "It has no second sentence or paragraph to split it at."
        case "merge":
            if before is None:
                return (
                    "It is the first clause at its level, so there is no clause before it to "
                    "merge with."
                )
            if "table" in (part.kind, before.kind):
                return "A table is not merged: its rows are read from the table itself."
            family, before_family = FAMILIES.get(part.kind), FAMILIES.get(before.kind)
            if family != before_family:
                if before_family == "heading":
                    return "The clause before it is a heading: move this one under it instead."
                if family == "heading":
                    return "It is a heading, and the clause before it is text. Make it text first."
                return "A row is merged only with the row before it."
        case "make-text":
            if part.kind == "table":
                return "A table's column names stay its heading."
            if part.kind != "section" or part.heading is None:
                return "It is text already."
        case "make-heading":
            if part.kind == "section":
                return "It is a heading already."
            if part.kind != "paragraph":
                return "Only a paragraph of text can be made a heading."
            if len(part.lines) != 1:
                return (
                    f"A heading is one paragraph, and this clause has {len(part.lines)}. "
                    "Split it first."
                )
        case "move-under":
            if before is None:
                return (
                    "It is the first clause at its level, so there is no clause before it to "
                    "move it under."
                )
        case "move-out":
            if parent is None:
                return "It is at the top level already."
    return None


def _check(roots: list[Part], part: Part, edit: Edit) -> tuple[Part | None, list[Part], int]:
    parent, siblings, index = _place(roots, part)
    refused = refusal(part, parent, siblings, index, edit)
    if refused is not None:
        raise CannotFix(refused)
    return parent, siblings, index


def split(roots: list[Part], part: Part, at: int, texts: dict[int, str]) -> Result:
    _, siblings, index = _check(roots, part, "split")
    text = part.text
    if at not in boundaries(text):
        raise CannotFix(
            "A clause is split where a sentence or a paragraph begins, and none begins there."
        )
    row = text.count("\n", 0, at)
    column = at - (text.rfind("\n", 0, at) + 1)
    lines = part.lines
    # Inside a line, both parts hold its paragraph; at the start of one, the second part does.
    inside = bool(lines[row][:column].strip())
    if inside:
        first = [*lines[:row], lines[row][:column].rstrip()]
        second = [lines[row][column:].lstrip(), *lines[row + 1 :]]
    else:
        first, second = lines[:row], [lines[row].lstrip(), *lines[row + 1 :]]
    # A part takes no empty line from the edges of the split.
    while first and not first[-1].strip():
        first.pop()
    while second and not second[0].strip():
        second.pop(0)

    places = _line_places(part, texts)
    head = part.positions[:1] if part.kind == "section" else []
    if places is None:
        # Lines the file as read cannot place: the second part holds the clause's last paragraph.
        first_places, second_places = list(part.positions), part.positions[-1:]
    elif inside:
        first_places, second_places = head + places[: row + 1], places[row:]
    else:
        first_places, second_places = head + places[:row], places[row:]

    label: str | None = None
    numbered = opening_number(second[0]) if second else None
    if numbered is not None:
        label, second[0] = numbered
    other = Part(
        kind="list" if part.kind == "list" else "paragraph",
        layer="reviewer",
        label=label,
        heading=None,
        lines=second,
        positions=list(dict.fromkeys(second_places)),
    )
    part.lines = first
    part.positions = list(dict.fromkeys(first_places))
    siblings.insert(index + 1, other)
    marked = _mark("split", part, other)
    return Result(part, part, other, reworded=[part, other], gone=[], marked=marked)


def _words_of(part: Part) -> list[str]:
    """A clause's words as lines of text, its number and heading first, as they stand in the
    file, for a merge that leaves it no number or heading of its own."""
    lead = " ".join(filter(None, [part.label, part.heading]))
    if part.heading is not None or not part.lines:
        return [lead, *part.lines] if lead else list(part.lines)
    first = " ".join(filter(None, [part.label, part.lines[0]]))
    return [first, *part.lines[1:]]


def merge(roots: list[Part], part: Part) -> Result:
    _, siblings, index = _check(roots, part, "merge")
    before = siblings[index - 1]
    if part.kind == "section":
        heading = " ".join(filter(None, [part.label, part.heading]))
        before.heading = "\n".join(filter(None, [before.heading, heading]))
        before.lines.extend(part.lines)
    else:
        before.lines.extend(_words_of(part))
    before.positions.extend(part.positions)
    before.children.extend(part.children)
    del siblings[index]
    marked = _mark("merged", before)
    return Result(part, before, before, reworded=[before], gone=[part], marked=marked)


def make_text(roots: list[Part], part: Part) -> Result:
    _, siblings, index = _check(roots, part, "make-text")
    part.kind = "paragraph"
    part.lines = [part.heading or "", *part.lines]
    part.heading = None
    followers, part.children = part.children, []
    siblings[index + 1 : index + 1] = followers
    marked = _mark("made-text", part) + _mark("moved-out", *followers)
    return Result(part, part, None, reworded=[], gone=[], marked=marked)


def make_heading(roots: list[Part], part: Part) -> Result:
    _check(roots, part, "make-heading")
    part.kind = "section"
    part.heading = part.lines[0]
    part.lines = []
    return Result(part, part, None, reworded=[], gone=[], marked=_mark("made-heading", part))


def move_under(roots: list[Part], part: Part) -> Result:
    _, siblings, index = _check(roots, part, "move-under")
    before = siblings[index - 1]
    del siblings[index]
    before.children.append(part)
    return Result(part, part, before, reworded=[], gone=[], marked=_mark("moved-under", part))


def move_out(roots: list[Part], part: Part) -> Result:
    parent, siblings, index = _check(roots, part, "move-out")
    assert parent is not None
    _, outer, at = _place(roots, parent)
    followers = siblings[index + 1 :]
    del siblings[index:]
    if part.kind == "section":
        part.children.extend(followers)
        outer.insert(at + 1, part)
        marked = _mark("moved-out", part) + _mark("moved-under", *followers)
    else:
        outer[at + 1 : at + 1] = [part, *followers]
        marked = _mark("moved-out", part, *followers)
    return Result(part, part, None, reworded=[], gone=[], marked=marked)


def apply(
    roots: list[Part],
    edit: Edit,
    part: Part,
    at: int | None = None,
    texts: dict[int, str] | None = None,
) -> Result:
    """Make one edit to the tree, in place, or refuse it with why."""
    if edit == "split":
        if at is None:
            raise CannotFix("Say where to split it: where in its text the second part begins.")
        return split(roots, part, at, texts or {})
    tools: dict[Edit, Callable[[list[Part], Part], Result]] = {
        "merge": merge,
        "make-text": make_text,
        "make-heading": make_heading,
        "move-under": move_under,
        "move-out": move_out,
    }
    return tools[edit](roots, part)


def fixes(roots: list[Part]) -> dict[str, list[Edit]]:
    """For every clause, by key, the edits that can be made to it where it sits."""
    found: dict[str, list[Edit]] = {}

    def visit(parent: Part | None, siblings: list[Part]) -> None:
        for index, part in enumerate(siblings):
            found[part.key] = [
                edit for edit in EDITS if refusal(part, parent, siblings, index, edit) is None
            ]
            visit(part, part.children)

    visit(None, roots)
    return found


def possible(roots: list[Part], edit: Edit, key: str, at: int | None = None) -> bool:
    """Whether an edit could be made now, and for a split, there."""
    part = locate(roots, key)
    if part is None:
        return False
    parent, siblings, index = _place(roots, part)
    if refusal(part, parent, siblings, index, edit) is not None:
        return False
    return edit != "split" or at in boundaries(part.text)


def keyed(slug: str, roots: list[Part]) -> tuple[Clause, ...]:
    """Give every clause its key by the rules a parse uses, and the tree as a parse returns it."""

    def node(part: Part) -> Node:
        # One line holding the whole text, so a blank line inside a paragraph stays in it.
        return Node(
            kind=part.kind,
            layer=part.layer,
            label=part.label,
            heading=part.heading,
            lines=[part.text] if part.text.strip() else [],
            positions=list(part.positions),
            children=[node(child) for child in part.children],
        )

    clauses = assign(slug, [node(part) for part in roots])

    def pair(parts: list[Part], found: tuple[Clause, ...]) -> None:
        for part, clause in zip(parts, found, strict=True):
            part.key = clause.key
            part.lang = clause.lang
            pair(part.children, clause.children)

    pair(roots, clauses)
    return clauses
