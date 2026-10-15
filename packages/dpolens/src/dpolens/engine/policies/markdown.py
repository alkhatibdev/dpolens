"""Reading a Markdown file, with a CommonMark parser.

Headings, lists, tables and paragraphs come from markdown-it-py, which knows a "#" inside a
code block from a heading and an underlined line from a rule, where a reader written here
would guess. Text is kept as a reader sees it: the words, without the marks for emphasis and
links.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

from dpolens.engine.policies.blocks import (
    Item,
    Number,
    Paragraph,
    ReadFile,
    Row,
    Table,
    UnreadablePolicy,
)

FRONT_MATTER = re.compile(r"\A(---[ \t]*\n.*?\n)(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.DOTALL)
TAG = re.compile(r"<[^>]*>")


@dataclass
class ListAt:
    identity: str
    ordered: bool
    next: int = 1
    """The number the next item shows. Markdown numbers a list from its first item, whatever
    the later items are written as, so "1. 1. 1." reads 1, 2, 3."""


class Walker:
    def __init__(self, tokens: list[Token], offset: int) -> None:
        self.tokens = tokens
        self.offset = offset
        self.at = 0
        self.position = 0
        self.lists: list[ListAt] = []
        self.made = 0
        self.items: list[Item] = []
        self.unread: set[str] = set()
        self.pending: Number | None = None
        """The number of the list item whose first paragraph is next."""

        self.in_item = 0

    def line(self, token: Token) -> int | None:
        return token.map[0] + 1 + self.offset if token.map else None

    def paragraph(self, inline: Token, start: Token, heading: int | None = None) -> Paragraph:
        text, bold = render(inline)
        number, continues = None, False
        if self.pending is not None:
            number, self.pending = self.pending, None
        elif self.in_item and heading is None:
            continues = True
        paragraph = Paragraph(
            position=self.position,
            text=text,
            heading_level=heading,
            number=number,
            bold=bold,
            continues=continues,
            line=self.line(start),
        )
        self.position += 1
        return paragraph

    def walk(self) -> list[Item]:
        while self.at < len(self.tokens):
            token = self.tokens[self.at]
            kind = token.type
            if kind == "heading_open":
                level = int(token.tag[1:])
                self.items.append(self.paragraph(self.tokens[self.at + 1], token, level))
                self.at += 3
                continue
            if kind == "paragraph_open":
                self.items.append(self.paragraph(self.tokens[self.at + 1], token))
                self.at += 3
                continue
            if kind in ("bullet_list_open", "ordered_list_open"):
                self.made += 1
                start = token.attrGet("start")
                self.lists.append(
                    ListAt(
                        f"list-{self.made}",
                        kind == "ordered_list_open",
                        int(start) if isinstance(start, (int, str)) and str(start).isdigit() else 1,
                    )
                )
            elif kind in ("bullet_list_close", "ordered_list_close"):
                self.lists.pop()
            elif kind == "list_item_open":
                current = self.lists[-1]
                label = f"{current.next}{token.markup}" if current.ordered else "•"
                current.next += 1
                self.pending = Number(
                    label=label,
                    list_id=current.identity,
                    level=len(self.lists) - 1,
                    bullet=not current.ordered,
                )
                self.in_item += 1
            elif kind == "list_item_close":
                self.in_item -= 1
                self.pending = None
            elif kind == "table_open":
                self.items.append(self.table())
                continue
            elif kind in ("fence", "code_block"):
                self.items.append(self.verbatim(token.content.rstrip("\n"), token))
            elif kind == "html_block":
                text = TAG.sub("", token.content).strip()
                if text:
                    self.items.append(self.verbatim(text, token))
            elif kind not in ("hr", "blockquote_open", "blockquote_close"):
                self.unread.add(kind)
            self.at += 1
        return self.items

    def verbatim(self, text: str, token: Token) -> Paragraph:
        number, self.pending = self.pending, None
        paragraph = Paragraph(
            position=self.position,
            text=text,
            number=number,
            continues=number is None and self.in_item > 0,
            line=self.line(token),
        )
        self.position += 1
        return paragraph

    def table(self) -> Table:
        start = self.position
        rows: list[Row] = []
        cells: list[tuple[Paragraph, ...]] = []
        header = False
        self.at += 1
        while self.tokens[self.at].type != "table_close":
            token = self.tokens[self.at]
            if token.type == "thead_open":
                header = True
            elif token.type == "thead_close":
                header = False
            elif token.type == "tr_close":
                rows.append(Row(cells=tuple(cells), header=header))
                cells = []
            elif token.type in ("th_open", "td_open"):
                inline = self.tokens[self.at + 1]
                text, bold = render(inline)
                cell = Paragraph(
                    position=self.position,
                    text=text,
                    place="cell",
                    bold=bold,
                    line=self.line(token) or self.line(inline),
                )
                self.position += 1
                cells.append((cell,))
            self.at += 1
        self.at += 1
        return Table(position=start, rows=tuple(rows))


def render(inline: Token) -> tuple[str, bool]:
    """An inline token's text as a reader sees it, and whether all of it is bold."""
    parts: list[str] = []
    strong = 0
    bold = True
    for child in inline.children or []:
        kind = child.type
        if kind == "strong_open":
            strong += 1
        elif kind == "strong_close":
            strong -= 1
        elif kind in ("text", "code_inline"):
            parts.append(child.content)
            if child.content.strip() and not strong:
                bold = False
        elif kind == "softbreak":
            parts.append(" ")
        elif kind == "hardbreak":
            parts.append("\n")
        elif kind == "image":
            parts.append(child.content)
            bold = bold and bool(strong)
    text = "".join(parts)
    return text, bold and bool(text.strip())


def read_markdown(data: bytes) -> ReadFile:
    """Read a Markdown file into paragraphs and tables."""
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnreadablePolicy("This Markdown file is not UTF-8 text.") from error
    items: list[Item] = []
    offset = 0
    front = FRONT_MATTER.match(source)
    if front:
        items.append(Paragraph(position=0, text=front.group(1)[4:].strip(), place="front matter"))
        offset = front.group(0).count("\n")
        source = source[front.end() :]
    parser = MarkdownIt("commonmark").enable("table")
    walker = Walker(parser.parse(source), offset)
    walker.position = len(items)
    items.extend(walker.walk())
    notices: tuple[str, ...] = ()
    if walker.unread:
        notices = (f"Parts of this file were not read: {', '.join(sorted(walker.unread))}.",)
    return ReadFile(format="markdown", items=tuple(items), notices=notices)
