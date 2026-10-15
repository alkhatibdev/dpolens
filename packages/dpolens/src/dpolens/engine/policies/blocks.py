"""What a reader makes of a file, before anything is decided.

A Word file and a Markdown file are read into the same paragraphs and tables, so the layers
that build the tree never ask which format they are looking at. Each paragraph carries every
signal a layer might use, and its position, which is where it sits in the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Place = Literal["body", "cell", "text box", "contents", "front matter"]
"""Where a paragraph sits. A text box, a contents page and a file's front matter are set aside."""


@dataclass(frozen=True)
class Number:
    """A number the file's own list machinery puts before a paragraph, as a reader sees it."""

    label: str
    """As shown: "4.2.", "(a)", "1-1", or "•" for a bullet."""

    list_id: str
    """Which list it belongs to, so two lists that look alike stay apart."""

    level: int
    """Its depth within that list, from 0."""

    bullet: bool


@dataclass(frozen=True)
class Paragraph:
    position: int
    """Its place among the file's paragraphs, counting those in tables and text boxes."""

    text: str
    """Verbatim, including any number typed into it. An automatic number is not text."""

    place: Place = "body"
    style: str | None = None
    heading_level: int | None = None
    """1 for the highest, from a heading style, an outline level or a Markdown heading."""

    title: bool = False
    """The file itself marks this as the document's title."""

    number: Number | None = None
    bold: bool = False
    """Every visible character is bold."""

    size: float | None = None
    """The largest font size in it, in points, where the format has sizes."""

    centred: bool = False
    capitals: bool = False
    continues: bool = False
    """It carries on the list item before it, as a list item's second paragraph does."""

    line: int | None = None
    """The line it starts on, in a format that has lines."""


@dataclass(frozen=True)
class Row:
    cells: tuple[tuple[Paragraph, ...], ...]
    header: bool = False
    """The file marks the row as a header, repeated on every page or Markdown's first row."""


@dataclass(frozen=True)
class Table:
    position: int
    """The position of its first paragraph."""

    rows: tuple[Row, ...]

    def paragraphs(self) -> list[Paragraph]:
        return [paragraph for row in self.rows for cell in row.cells for paragraph in cell]


Item = Paragraph | Table


class UnreadablePolicy(Exception):
    """The file cannot be read as a policy. The message says why, to whoever uploaded it."""


@dataclass(frozen=True)
class ReadFile:
    """A file as its reader found it."""

    format: Literal["docx", "markdown"]
    items: tuple[Item, ...]
    missed: int = 0
    """Characters of text the file holds that no paragraph took. Counted apart from the walk
    that builds the paragraphs, so a construct the reader does not know shows up here."""

    unread: tuple[str, ...] = ()
    """The kinds of element that held the missed text."""

    notices: tuple[str, ...] = ()
    """What a reviewer should know about the file as a whole, such as tracked changes."""

    def paragraphs(self) -> list[Paragraph]:
        found: list[Paragraph] = []
        for item in self.items:
            found.extend(item.paragraphs() if isinstance(item, Table) else [item])
        return found
