"""The file as it was read: what a reviewer sees beside the clauses.

Every paragraph the reader found, in the file's order, with what it looked like (a title, a
heading and its level, a number, bold) and where it sat, a table's cells keeping their row and
column. It is kept with the version when the file is read, so it always matches the positions
the clauses point at.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from dpolens.engine.policies.blocks import Paragraph, Place, ReadFile, Table


@dataclass(frozen=True)
class Line:
    """One paragraph of the file, as the reader found it."""

    position: int
    text: str
    place: Place = "body"
    heading: int | None = None
    """1 for the highest, when the file makes it a heading."""

    title: bool = False
    label: str | None = None
    """The number the file's own list machinery shows before it, or "•" for a bullet."""

    bold: bool = False
    table: int | None = None
    """Which of the file's tables it is in, from 0, with its row and cell."""

    row: int | None = None
    cell: int | None = None
    header: bool = False
    """Its row is the table's header."""


def _line(
    paragraph: Paragraph,
    table: int | None = None,
    row: int | None = None,
    cell: int | None = None,
    header: bool = False,
) -> Line:
    return Line(
        position=paragraph.position,
        text=paragraph.text,
        place=paragraph.place,
        heading=paragraph.heading_level,
        title=paragraph.title,
        label=paragraph.number.label if paragraph.number is not None else None,
        bold=paragraph.bold,
        table=table,
        row=row,
        cell=cell,
        header=header,
    )


def lines_of(read: ReadFile) -> tuple[Line, ...]:
    found: list[Line] = []
    tables = 0
    for item in read.items:
        if not isinstance(item, Table):
            found.append(_line(item))
            continue
        for row_at, row in enumerate(item.rows):
            for cell_at, cell in enumerate(row.cells):
                found.extend(
                    _line(paragraph, tables, row_at, cell_at, row.header) for paragraph in cell
                )
        tables += 1
    return tuple(sorted(found, key=lambda line: line.position))


def as_rows(lines: tuple[Line, ...]) -> list[dict[str, Any]]:
    return [asdict(line) for line in lines]


def from_rows(rows: list[dict[str, Any]]) -> tuple[Line, ...]:
    return tuple(Line(**row) for row in rows)
