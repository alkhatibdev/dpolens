"""A parsed policy: its clauses, what was set aside, and what a reviewer must look at."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dpolens.engine.policies.reading import Line

Layer = Literal["native_structure", "typography", "numbering", "reviewer"]
"""Which layer decided where a clause begins and how deep it sits: the file, its type, a number
typed into it, or a reviewer who fixed how it was read."""

Edit = Literal["split", "merge", "make-text", "make-heading", "move-under", "move-out"]
"""How a reviewer fixes what was read, without changing a word."""

FlagKind = Literal["coverage_gap", "numbering_gap", "low_confidence_boundary", "unmatched_key"]
Reason = Literal["title", "front matter", "contents", "text box", "repeated table"]


@dataclass(frozen=True)
class Clause:
    key: str
    kind: str
    """section, paragraph, list, table or row."""

    layer: Layer
    label: str | None
    """The number the document shows for it, such as "4.2." or "(a)"."""

    heading: str | None
    text: str
    """Verbatim, paragraph by paragraph, with a bullet before each item of a list."""

    lang: str
    positions: tuple[int, ...]
    """Where its paragraphs sit in the file."""

    children: tuple[Clause, ...] = ()

    def walk(self) -> list[Clause]:
        """This clause and everything beneath it, depth first."""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


@dataclass(frozen=True)
class SetAside:
    """Text that is in the file but in no clause, and why: never dropped, never searched."""

    reason: Reason
    text: str
    positions: tuple[int, ...]


@dataclass(frozen=True)
class Suggestion:
    """The fix the parser would make, when it knows one: an edit, and the clause it applies to
    when that is not the flag's own."""

    edit: Edit
    key: str | None = None
    at: int | None = None
    """For a split, where in the clause's text the second part begins."""

    label: str | None = None
    """For a split, the number the second part starts with."""


@dataclass(frozen=True)
class Flag:
    """Something the layers could not settle, for the reviewer to resolve or accept."""

    kind: FlagKind
    detail: str
    key: str | None = None
    position: int | None = None
    suggestion: Suggestion | None = None


@dataclass(frozen=True)
class Coverage:
    """Where every character of the file went."""

    characters: int
    in_clauses: int
    set_aside: int
    missed: int

    @property
    def complete(self) -> bool:
        return self.missed == 0 and self.in_clauses + self.set_aside == self.characters


@dataclass(frozen=True)
class ParsedPolicy:
    slug: str
    format: Literal["docx", "markdown"]
    title: str | None
    clauses: tuple[Clause, ...]
    set_aside: tuple[SetAside, ...]
    flags: tuple[Flag, ...]
    coverage: Coverage
    notices: tuple[str, ...]
    lines: tuple[Line, ...] = ()
    """The file as it was read, paragraph by paragraph."""

    def walk(self) -> list[Clause]:
        found: list[Clause] = []
        for clause in self.clauses:
            found.extend(clause.walk())
        return found
