"""The layers: from a file's paragraphs to a tree of clauses.

Each paragraph is asked, in order, what the file itself says about it (a heading style, an
outline level, an automatic number), what its type says (bold, size, capitals), and whether it
starts with a number written into its text. The first layer with an answer decides where a
clause begins and how deep it sits; the others corroborate, and where they disagree the
paragraph gets a flag rather than a quiet choice.

Depth follows the rule legal publishers used long before software: a new style of heading or
number goes one level deeper, and a style seen before jumps back up to where it was.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from dpolens.engine.policies.blocks import Item, Number, Paragraph, ReadFile, Row, Table
from dpolens.engine.policies.patterns import Label, parse_label, read_label
from dpolens.engine.policies.tree import Flag, FlagKind, Layer, Reason, SetAside

HEADING_WORDS = 30
"""Past this many words a paragraph styled as a heading is text, and past eight so is one that
ends a sentence."""

TYPED_HEADING_WORDS = 12
"""Bold or larger type marks a heading only on a line this short."""

SENTENCE_END = (".", "!", "؛", "۔")
"""A heading may ask a question; it does not end with a full stop."""

NAMED_HEADING = re.compile(r"^(heading [1-9]|title)$", re.IGNORECASE)
CONTENTS_WORDS = {
    "contents", "table of contents", "index", "المحتويات", "قائمة المحتويات",
    "فهرس المحتويات", "الفهرس", "جدول المحتويات",
}  # fmt: skip
PAGE_NUMBER = re.compile(r"\t\s*\d+\s*$")

Marker = tuple[str, ...]
"""What placed a clause, such as ("style", "2"), ("type", "0016.001"), ("list", id, "1") or
("typed", "1.")."""


@dataclass
class Node:
    kind: str
    layer: Layer
    label: str | None = None
    heading: str | None = None
    lines: list[str] = field(default_factory=list)
    positions: list[int] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    marker: Marker | None = None
    listed: tuple[str, int] | None = None
    """The automatic list and level its number comes from."""

    container: bool = False
    """It takes plain paragraphs as its own: a heading does, a numbered sentence does not."""

    @property
    def style(self) -> str | None:
        """Its number's style, "hyphenated-2" for "3-1", for lists that are lists only in look."""
        found = parse_label(self.label) if self.label else None
        return found.style if found is not None and not found.bullet else None

    def take(self, paragraph: Paragraph, line: str | None = None) -> None:
        """Hold a paragraph: its line of text, and its place in the file."""
        if line is not None or paragraph.text.strip():
            self.lines.append(paragraph.text if line is None else line)
        self.positions.append(paragraph.position)


@dataclass
class Built:
    """The tree before its keys, and what did not go into it."""

    roots: list[Node]
    set_aside: list[SetAside]
    flags: list[Flag]
    title: str | None
    spacing: list[int]
    """Positions of paragraphs with nothing in them but space."""


def words(text: str) -> int:
    return len(text.split())


def ends_a_sentence(text: str) -> bool:
    return text.rstrip().endswith(SENTENCE_END)


@dataclass(frozen=True)
class Signals:
    """Everything the layers know about one paragraph."""

    paragraph: Paragraph
    typed: tuple[Label, str] | None
    style_heading: bool
    """Its style or outline level makes it a heading, and it reads as one."""

    styled_as_text: bool
    """It has a Heading style but reads as a paragraph of text, which a reviewer should see.

    A paragraph that only inherits an outline level from its style, as body styles in some
    templates do, is read as text without a flag."""

    type_heading: bool
    """Bold, larger or in capitals, short, and not a lead-in to a list."""

    marked: bool
    """Set apart by its type: bold, larger than the text around it, or in capitals."""

    @property
    def number(self) -> str | None:
        found = self.paragraph.number
        return found.label if found is not None and not found.bullet else None

    @property
    def bullet(self) -> bool:
        found = self.paragraph.number
        typed_bullet = self.typed is not None and self.typed[0].bullet
        return (found is not None and found.bullet) or (found is None and typed_bullet)

    @property
    def typed_number(self) -> tuple[Label, str] | None:
        if self.typed is None or self.typed[0].bullet or self.paragraph.number is not None:
            return None
        return self.typed

    @property
    def heading_like(self) -> bool:
        """Whether a numbered paragraph heads what follows it, or is a clause of its own.

        Being short is not enough: "Securely kept" in a numbered list is a clause. A heading
        also looks like one: its style, bold, larger type or capitals.
        """
        text = self.typed[1] if self.typed_number is not None and self.typed else None
        text = (text if text is not None else self.paragraph.text).strip()
        if self.style_heading:
            return True
        short = 0 < words(text) <= TYPED_HEADING_WORDS
        return short and not ends_a_sentence(text) and self.marked


def read_signals(paragraph: Paragraph, body_size: float | None) -> Signals:
    text = paragraph.text.strip()
    styled = paragraph.heading_level is not None and bool(text)
    reads_as_text = styled and (
        words(text) > HEADING_WORDS or (ends_a_sentence(text) and words(text) > 8)
    )
    larger = (
        body_size is not None and paragraph.size is not None and paragraph.size >= body_size + 1.5
    )
    marked = paragraph.bold or larger or (paragraph.capitals and words(text) >= 2)
    type_heading = (
        not styled
        and marked
        and 0 < words(text) <= TYPED_HEADING_WORDS
        and not ends_a_sentence(text)
        and not text.endswith(":")
        and paragraph.number is None
        and any(character.isalpha() for character in text)
    )
    named = paragraph.style is None or bool(NAMED_HEADING.match(paragraph.style))
    return Signals(
        paragraph=paragraph,
        typed=read_label(paragraph.text) if text else None,
        style_heading=styled and not reads_as_text,
        styled_as_text=reads_as_text and named,
        type_heading=type_heading,
        marked=marked,
    )


def body_size(paragraphs: Sequence[Paragraph]) -> float | None:
    """The size most of the text is set in, which is what larger type is larger than."""
    sizes: Counter[float] = Counter()
    for paragraph in paragraphs:
        if paragraph.size is not None and paragraph.heading_level is None:
            sizes[paragraph.size] += len(paragraph.text)
    return sizes.most_common(1)[0][0] if sizes else None


def type_rank(paragraph: Paragraph, body: float | None) -> str:
    """Larger type ranks higher, then capitals, then bold, as a sortable string."""
    size = paragraph.size if paragraph.size is not None else (body or 0.0)
    return f"{size:06.1f}{int(paragraph.capitals)}{int(paragraph.bold)}"


class Builder:
    def __init__(self, read: ReadFile) -> None:
        self.read = read
        everything = read.paragraphs()
        self.body_size = body_size([p for p in everything if p.place in ("body", "cell")])
        self.root = Node(kind="document", layer="native_structure", container=True)
        self.stack: list[Node] = [self.root]
        self.set_aside: list[SetAside] = []
        self.flags: list[Flag] = []
        self.title: str | None = None
        self.last: Node | None = None
        """The clause the previous paragraph went into, which a bullet or a continuation joins."""

        self.tables_seen: set[tuple[tuple[str, ...], ...]] = set()
        self.titled: set[int] = set()
        """Where, in the file's items, paragraphs name the document rather than open it."""
        self.spacing: list[int] = []
        """Positions of paragraphs with nothing in them but space."""
        self.open_table: tuple[list[tuple[int, Node]], Node | None] | None = None
        """The sections a table left open, which a table straight after it carries on: Word
        splits one table into several when a row's layout changes."""

    @property
    def top(self) -> Node:
        return self.stack[-1]

    def aside(self, reason: Reason, paragraphs: Sequence[Paragraph]) -> None:
        texts = [p.text for p in paragraphs]
        if not paragraphs:
            return
        previous = self.set_aside[-1] if self.set_aside else None
        if (
            previous is not None
            and previous.reason == reason
            and previous.positions
            and (previous.positions[-1] + 1 == paragraphs[0].position)
        ):
            self.set_aside[-1] = SetAside(
                reason=previous.reason,
                text="\n".join([previous.text, *texts]),
                positions=(*previous.positions, *(p.position for p in paragraphs)),
            )
            return
        self.set_aside.append(
            SetAside(
                reason=reason,
                text="\n".join(texts),
                positions=tuple(p.position for p in paragraphs),
            )
        )

    def flag(self, kind: FlagKind, detail: str, position: int | None = None) -> None:
        self.flags.append(Flag(kind=kind, detail=detail, position=position))

    # The stack ---------------------------------------------------------------------------

    def find(self, test: Callable[[Node], bool]) -> int | None:
        for index in range(len(self.stack) - 1, 0, -1):
            if test(self.stack[index]):
                return index
        return None

    def place(self, node: Node) -> None:
        """Put a heading or numbered clause where its marker says, and open it."""
        marker = node.marker or ()
        family = marker[0] if marker else ""
        if family == "style":
            while len(self.stack) > 1:
                top = self.top.marker
                if top is not None and top[0] == "style" and top[1] < marker[1]:
                    break
                self.stack.pop()
        elif family == "type":
            while len(self.stack) > 1:
                top = self.top.marker
                if top is not None and (
                    top[0] == "style" or (top[0] == "type" and top[1] > marker[1])
                ):
                    break
                self.stack.pop()
        elif node.listed is not None:
            list_id, level = node.listed
            found = self.find(
                lambda open_: (
                    open_.listed is not None
                    and open_.listed[0] == list_id
                    and open_.listed[1] <= level
                )
            )
            if found is not None:
                listed = self.stack[found].listed
                assert listed is not None
                del self.stack[found if listed[1] == level else found + 1 :]
            elif node.style is not None:
                # Each item its own one-item list, as copied or templated documents have:
                # the number's style still says which ones are siblings, among items like it.
                style, kind = node.style, node.kind
                found = self.find(
                    lambda open_: (
                        open_.marker is not None
                        and open_.marker[0] == "list"
                        and open_.kind == kind
                        and open_.style == style
                    )
                )
                if found is not None:
                    del self.stack[found:]
        elif family == "typed":
            found = self.find(lambda open_: open_.marker == marker)
            if found is not None:
                del self.stack[found:]
        self.top.children.append(node)
        self.stack.append(node)
        self.last = node

    def container(self) -> Node:
        """The nearest open clause that takes plain paragraphs: a heading, or the document."""
        for node in reversed(self.stack):
            if node.container:
                return node
        return self.root

    # Paragraphs --------------------------------------------------------------------------

    def paragraph(self, signals: Signals) -> None:
        paragraph = signals.paragraph
        text = paragraph.text
        if not text.strip() and signals.number is None:
            # Spacing: it holds no text, so recording where it was is all it needs.
            self.spacing.append(paragraph.position)
            return
        self.open_table = None
        if paragraph.continues and self.last is not None:
            self.last.take(paragraph)
            return
        if signals.bullet:
            self.bulleted(signals)
            return
        if signals.styled_as_text:
            self.flag(
                "low_confidence_boundary",
                "Styled as a heading but reads as a paragraph, so it was kept as text.",
                paragraph.position,
            )
        typed = signals.typed_number
        if typed is not None and typed[0].style.startswith("word-") and not signals.heading_like:
            # "Section 3 of the Act requires ..." opens a sentence; it numbers nothing.
            typed = None
        if signals.number is not None:
            label, rest = signals.number, text.strip()
        elif typed is not None:
            label, rest = typed[0].text, typed[1].strip()
        else:
            label, rest = None, text.strip()
        if signals.style_heading:
            marker = ("style", str(paragraph.heading_level))
            self.heading(signals, label, rest, marker, "native_structure")
        elif signals.number is not None:
            self.numbered(signals, label, rest, None, "native_structure")
        elif typed is not None:
            self.numbered(signals, label, rest, typed[0], "numbering")
        elif signals.type_heading:
            marker = ("type", type_rank(paragraph, self.body_size))
            self.heading(signals, label, rest, marker, "typography")
        else:
            node = Node(kind="paragraph", layer="native_structure")
            node.take(paragraph)
            self.container().children.append(node)
            self.last = node

    def heading(
        self, signals: Signals, label: str | None, rest: str, marker: Marker, layer: Layer
    ) -> None:
        paragraph = signals.paragraph
        node = Node(
            kind="section",
            layer=layer,
            label=label,
            heading=rest,
            marker=marker,
            container=True,
        )
        if paragraph.number is not None and not paragraph.number.bullet:
            node.listed = (paragraph.number.list_id, paragraph.number.level)
        node.positions.append(paragraph.position)
        self.place(node)

    def numbered(
        self, signals: Signals, label: str | None, rest: str, typed: Label | None, layer: Layer
    ) -> None:
        """A numbered paragraph: a heading over what follows if it looks like one, else a
        clause with its own text, which deeper numbers can still sit under."""
        paragraph = signals.paragraph
        heading_like = signals.heading_like
        node = Node(
            kind="section" if heading_like else "paragraph",
            layer=layer,
            label=label,
            heading=rest if heading_like else None,
            container=heading_like,
        )
        if not heading_like:
            node.lines.append(rest)
        node.positions.append(paragraph.position)
        if paragraph.number is not None and not paragraph.number.bullet:
            node.listed = (paragraph.number.list_id, paragraph.number.level)
            node.marker = ("list", paragraph.number.list_id, str(paragraph.number.level))
        elif typed is not None:
            node.marker = ("typed", typed.style)
        self.place(node)

    def bulleted(self, signals: Signals) -> None:
        paragraph = signals.paragraph
        level = paragraph.number.level if paragraph.number is not None else 0
        text = paragraph.text.strip()
        if signals.typed is not None and paragraph.number is None:
            text = signals.typed[1].strip()
        line = "  " * level + "• " + text
        target = self.last
        open_ = {id(node) for node in self.stack}
        joinable = (
            target is not None
            and target.kind in ("paragraph", "list")
            and (id(target) in open_ or any(target is child for child in self.top.children))
        )
        if not joinable or target is None:
            target = Node(kind="list", layer="native_structure")
            self.top.children.append(target)
        target.lines.append(line)
        target.positions.append(paragraph.position)
        self.last = target

    # Tables ------------------------------------------------------------------------------

    def table(self, table: Table) -> None:
        cells = signature(table)
        entries = sum(1 for row in cells for text in row if text)
        if cells in self.tables_seen and entries > 1:
            # A table printed again on later pages, as a document converted from a PDF has.
            self.aside("repeated table", table.paragraphs())
            return
        self.tables_seen.add(cells)
        widths = {sum(1 for cell in row.cells if filled(cell)) for row in table.rows}
        if max(widths, default=0) < 2:
            texts = [p.text.strip() for p in table.paragraphs() if p.text.strip()]
            if self.open_table is not None and len(texts) == 1 and len(table.rows) == 1:
                # A one-cell table between the tables of a run titles the rows after it.
                still_open, _ = self.open_table
                title = Node(kind="section", layer="native_structure", heading=texts[0])
                title.container = True
                for paragraph in table.paragraphs():
                    title.positions.append(paragraph.position)
                still_open[-1][1].children.append(title)
                self.open_table = (still_open, title)
                return
            # A single column places text rather than listing entries: read it as text.
            for paragraph in table.paragraphs():
                self.paragraph(read_signals(paragraph, self.body_size))
            return
        rows = list(table.rows)
        header: Row | None = None
        if rows[0].header or self.looks_like_header(rows):
            header = rows.pop(0)
        base = self.top if self.top.container else self.container()
        if header is not None:
            node = Node(
                kind="table",
                layer="native_structure",
                heading=" · ".join(
                    " ".join(p.text.strip() for p in cell).strip()
                    for cell in header.cells
                    if any(p.text.strip() for p in cell)
                ),
                container=True,
            )
            for cell in header.cells:
                for paragraph in cell:
                    node.positions.append(paragraph.position)
            base.children.append(node)
            base = node
        # Rows nest the way paragraphs do: a numbered row with a short title heads the rows
        # after it until one numbered as high or higher; a row merged across the table titles
        # the rows below it within that; any other row is an entry where it falls.
        sections: list[tuple[int, Node]] = [(-1, base)]
        group: Node | None = None
        if self.open_table is not None and header is None:
            sections, group = self.open_table
        widest = max(len(row.cells) for row in table.rows)
        ranks = [rank(row) for row in rows]
        for at, row in enumerate(rows):
            texts = [" ".join(p.text.strip() for p in cell).strip() for cell in row.cells]
            drawn = first_number(row)
            if len(row.cells) == 1 and widest > 1 and any(texts) and drawn is None:
                group = Node(
                    kind="section", layer="native_structure", heading=texts[0], container=True
                )
                for paragraph in [p for cell in row.cells for p in cell]:
                    group.positions.append(paragraph.position)
                sections[-1][1].children.append(group)
                continue
            entry = self.row(row, texts)
            depth = ranks[at]
            if depth is not None:
                while len(sections) > 1 and sections[-1][0] >= depth:
                    sections.pop()
                    group = None
                titled = len([t for t in texts[1:] if t]) == 1 and not texts[0]
                if titled and entry.lines and heads(ranks, at):
                    entry.kind, entry.heading, entry.lines = "section", entry.lines[0], []
                    entry.container = True
                    sections[-1][1].children.append(entry)
                    sections.append((depth, entry))
                    group = None
                    continue
            (group or sections[-1][1]).children.append(entry)
        self.last = None
        self.open_table = (sections, group)

    @staticmethod
    def looks_like_header(rows: list[Row]) -> bool:
        """Column names: a first row in bold over rows that are not, or, across three columns
        or more, a first row of short names over rows that are not all names."""

        def bold(row: Row) -> bool:
            filled = [p for cell in row.cells for p in cell if p.text.strip()]
            return bool(filled) and all(p.bold for p in filled)

        def names(row: Row) -> bool:
            texts = [" ".join(p.text.strip() for p in cell).strip() for cell in row.cells]
            filled = [text for text in texts if text]
            return len(filled) == len(texts) and all(
                words(text) <= 4 and not ends_a_sentence(text) and not text[:1].isdigit()
                for text in filled
            )

        if bold(rows[0]) and not all(bold(row) for row in rows[1:]):
            return True
        return len(rows[0].cells) >= 3 and names(rows[0]) and not all(names(r) for r in rows[1:])

    def row(self, row: Row, texts: list[str]) -> Node:
        first = row.cells[0] if row.cells else ()
        drawn = next(
            (p.number for p in first if p.number is not None and not p.number.bullet), None
        )
        typed = read_label(texts[0]) if texts and texts[0] else None
        label: str | None = None
        heading: str | None = None
        body = texts
        if drawn is not None:
            label = drawn.label
            body = [texts[0], *texts[1:]] if texts[0] else texts[1:]
        elif typed is not None and not typed[0].bullet and not typed[1].strip():
            label, body = typed[0].text, texts[1:]
        elif texts and 0 < words(texts[0]) <= TYPED_HEADING_WORDS:
            heading, body = texts[0], texts[1:]
        node = Node(kind="row", layer="native_structure", label=label, heading=heading)
        node.lines = [text for text in body if text]
        for cell in row.cells:
            for paragraph in cell:
                node.positions.append(paragraph.position)
        return node

    # The whole file ----------------------------------------------------------------------

    def build(self) -> Built:
        sequence = list(self.read.items)
        sequence = self.without_contents(sequence)
        start = self.body_start(sequence)
        while start in self.titled:
            start += 1
        self.front(sequence[:start])
        for item in sequence[start:]:
            if isinstance(item, Table):
                places = {p.place for p in item.paragraphs()}
                if item.rows and places <= {"text box", "contents"}:
                    self.aside(
                        "contents" if "contents" in places else "text box", item.paragraphs()
                    )
                else:
                    self.table(item)
                continue
            if item.place == "text box":
                self.aside("text box", [item])
            elif item.place == "contents":
                self.aside("contents", [item])
            elif item.place == "front matter":
                self.aside("front matter", [item])
            else:
                self.paragraph(read_signals(item, self.body_size))
        self.unnumbered_among_numbered(self.root)
        return Built(
            roots=self.root.children,
            set_aside=self.set_aside,
            flags=self.flags,
            title=self.title,
            spacing=self.spacing,
        )

    def without_contents(self, sequence: list[Item]) -> list[Item]:
        """Mark a contents page typed by hand: a "Contents" line and the entries after it, or a
        list whose every item names a heading further on, as a page of links does."""
        sequence = self.linked_contents(sequence)
        result: list[Item] = []
        in_contents = False
        for index, item in enumerate(sequence):
            if isinstance(item, Paragraph):
                text = item.text.strip().lower().rstrip(":")
                if text in CONTENTS_WORDS and item.place == "body":
                    in_contents = True
                    result.append(replace(item, place="contents"))
                    continue
                if in_contents and item.text.strip():
                    entry = self.entry(item.text)
                    # An entry ends in its page number, or names a heading that comes later.
                    # Two entries run together still start with the first one's heading.
                    repeated = any(
                        isinstance(other, Paragraph)
                        and (later := self.entry(other.text))
                        and (entry == later or entry.startswith(later + " "))
                        for other in sequence[index + 1 :]
                    )
                    if PAGE_NUMBER.search(item.text) or repeated:
                        result.append(replace(item, place="contents"))
                        continue
                    in_contents = False
            elif in_contents:
                in_contents = False
            result.append(item)
        return result

    def linked_contents(self, sequence: list[Item]) -> list[Item]:
        headings = {
            self.entry(item.text)
            for item in sequence
            if isinstance(item, Paragraph) and item.heading_level and item.text.strip()
        }
        marked = list(sequence)
        run: list[int] = []
        for index, item in enumerate([*sequence, None]):
            listed = (
                isinstance(item, Paragraph)
                and item.number is not None
                and self.entry(item.text) in headings
            )
            if listed:
                run.append(index)
                continue
            if len(run) >= 3:
                for at in run:
                    found = marked[at]
                    assert isinstance(found, Paragraph)
                    marked[at] = replace(found, place="contents")
            run = []
        return marked

    @staticmethod
    def entry(text: str) -> str:
        """A contents entry or heading, reduced to its words for comparing one with the other."""
        text = PAGE_NUMBER.sub("", text)
        found = read_label(text)
        if found is not None:
            text = found[1]
        return " ".join(text.lower().split())

    def body_start(self, sequence: list[Item]) -> int:
        """Where the policy itself begins, after its title, cover and metadata."""
        paragraphs = [
            (index, item)
            for index, item in enumerate(sequence)
            if isinstance(item, Paragraph) and item.place == "body" and item.text.strip()
        ]
        signals = {index: read_signals(p, self.body_size) for index, p in paragraphs}
        titled = [index for index, p in paragraphs if p.title]
        styled = [index for index, _ in paragraphs if signals[index].style_heading]
        levels = Counter(sequence_level(sequence[index]) for index in styled)
        if styled:
            first = styled[0]
            highest = min(levels)
            alone = levels[highest] == 1 and sequence_level(sequence[first]) == highest
            # A lone top heading names the document when headings sit below it, or when it is
            # centred as a title is; alone and plain, it is the document's one section.
            if alone and (len(styled) > 1 or self.centred(sequence[first])):
                titled.append(first)
        self.titled = set(titled)
        for index in titled:
            paragraph = sequence[index]
            assert isinstance(paragraph, Paragraph)
            self.title = self.title or paragraph.text.strip()
        candidates = [index for index in styled if index not in titled]
        repeated = Counter(sequence_level(sequence[index]) for index in candidates)
        top_levels = [level for level, count in repeated.items() if count >= 2]
        if top_levels:
            top = min(top_levels)
            tops = [index for index in candidates if sequence_level(sequence[index]) == top]
            numbered = [index for index in tops if self.numbered_paragraph(sequence[index])]
            if len(numbered) * 2 >= len(tops):
                lists: Counter[tuple[str, int]] = Counter()
                for index in numbered:
                    item = sequence[index]
                    if isinstance(item, Paragraph) and item.number is not None:
                        lists[(item.number.list_id, item.number.level)] += 1
                if lists:
                    list_id, level = lists.most_common(1)[0][0]
                    for index, p in paragraphs:
                        if p.number is not None and (p.number.list_id, p.number.level) == (
                            list_id,
                            level,
                        ):
                            return min(index, numbered[0])
                return numbered[0]
            uncentred = [index for index in tops if not self.centred(sequence[index])]
            return (uncentred or tops)[0]
        drawn = [
            index
            for index, p in paragraphs
            if p.number is not None and not p.number.bullet and signals[index].heading_like
        ]
        if drawn:
            return drawn[0]
        typed = [
            index
            for index, _ in paragraphs
            if signals[index].typed_number is not None and signals[index].heading_like
        ]
        if typed:
            return typed[0]
        if candidates:
            return candidates[0]
        headings = [index for index, _ in paragraphs if signals[index].type_heading]
        return headings[0] if headings else 0

    @staticmethod
    def numbered_paragraph(item: Item) -> bool:
        if not isinstance(item, Paragraph):
            return False
        if item.number is not None and not item.number.bullet:
            return True
        found = read_label(item.text)
        return found is not None and not found[0].bullet

    @staticmethod
    def centred(item: Item) -> bool:
        return isinstance(item, Paragraph) and item.centred

    def front(self, items: list[Item]) -> None:
        """Before the policy begins: a title, a cover and metadata are set aside; prose is kept."""
        for index, item in enumerate(items):
            if isinstance(item, Table):
                self.tables_seen.add(signature(item))
                self.aside("front matter", item.paragraphs())
                continue
            text = item.text.strip()
            if item.place in ("text box", "contents"):
                self.aside(item.place, [item])
            elif index in self.titled:
                self.aside("title", [item])
            elif (
                text
                and item.place == "body"
                and words(text) >= 8
                and not (item.bold or item.centred or item.capitals or item.heading_level)
            ):
                node = Node(kind="paragraph", layer="native_structure")
                node.take(item)
                self.root.children.append(node)
                self.last = node
            else:
                self.aside("front matter", [item])

    def unnumbered_among_numbered(self, node: Node) -> None:
        """A heading with no number among siblings that all have one is probably deeper."""
        sections = [child for child in node.children if child.kind == "section"]
        for child in sections:
            same = [other for other in sections if other.marker == child.marker]
            numbered = [other for other in same if other.label]
            if child.label is None and len(numbered) >= 2 and len(numbered) * 2 > len(same):
                self.flag(
                    "low_confidence_boundary",
                    f'"{child.heading}" has no number, unlike the headings around it, '
                    "so it may belong under the one before it.",
                    child.positions[0] if child.positions else None,
                )
        for child in node.children:
            self.unnumbered_among_numbered(child)


def filled(cell: tuple[Paragraph, ...]) -> bool:
    """A cell with text, or with an automatic number, which is content though it is not text."""
    return any(p.text.strip() or (p.number is not None and not p.number.bullet) for p in cell)


def first_number(row: Row) -> Number | None:
    """The automatic number in a row's first cell, which numbers the row."""
    first = row.cells[0] if row.cells else ()
    return next((p.number for p in first if p.number is not None and not p.number.bullet), None)


def rank(row: Row) -> int | None:
    """How deep a numbered row sits, from its number's parts: "1" is 1, "1-1" is 2.

    Read from the number rather than its list, because a table's titles and its entries are
    often numbered by different lists that each start at level one.
    """
    drawn = first_number(row)
    if drawn is None:
        return None
    parts = re.findall(r"[0-9٠-٩]+|[a-zA-Z]+|[أ-ي]", drawn.label)
    return max(len(parts), 1)


def heads(ranks: list[int | None], at: int) -> bool:
    """Whether a numbered row heads the rows after it: the next row is unnumbered or deeper."""
    if at + 1 >= len(ranks):
        return False
    mine, following = ranks[at], ranks[at + 1]
    return following is None or (mine is not None and following > mine)


def signature(table: Table) -> tuple[tuple[str, ...], ...]:
    """A table's text, cell by cell, for knowing a repeated table when it comes again."""
    return tuple(
        tuple(" ".join(p.text.strip() for p in cell).strip() for cell in row.cells)
        for row in table.rows
    )


def sequence_level(item: Item) -> int:
    return (item.heading_level or 0) if isinstance(item, Paragraph) else 0


def build(read: ReadFile) -> Built:
    return Builder(read).build()
