"""Reading a Word file from its XML, with the standard library alone.

A .docx is a zip of XML parts. This reads the main document part with its styles and list
definitions, and walks the body in order: paragraphs, tables, content controls, text boxes,
tracked changes and fields. Every piece of text is either taken into a paragraph or counted as
missed, apart from the walk, so a construct this does not know cannot lose text quietly.

The file is untrusted. The package's size is checked before anything is unpacked, and a part
that declares a DTD is refused, which rules out entity expansion altogether.
"""

from __future__ import annotations

import codecs
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from posixpath import dirname, join, normpath
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from dpolens.engine.policies.blocks import (
    Item,
    Number,
    Paragraph,
    Place,
    ReadFile,
    Row,
    Table,
    UnreadablePolicy,
)
from dpolens.engine.policies.numbering import Numbering

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

MAX_PARTS = 2_000
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024

HEADING_STYLE = re.compile(r"^heading ([1-9])$", re.IGNORECASE)
LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
)
"""Letters joined for print, as a PDF converted to Word keeps them: the same words, which a
search for "specific" has to find."""
ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
OFF = ("0", "false", "off")

# Elements that shape text without holding any of their own, or hold text that is not the
# document's: field codes, revision marks, bookmarks.
SKIPPED_IN_PARAGRAPH = frozenset(
    {
        "pPr", "rPr", "bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd",
        "commentRangeStart", "commentRangeEnd", "moveFromRangeStart", "moveFromRangeEnd",
        "moveToRangeStart", "moveToRangeEnd", "customXmlPr", "smartTagPr", "sdtPr",
        "sdtEndPr", "subDoc", "customXmlInsRangeStart", "customXmlInsRangeEnd",
        "customXmlDelRangeStart", "customXmlDelRangeEnd", "customXmlMoveFromRangeStart",
        "customXmlMoveFromRangeEnd", "customXmlMoveToRangeStart", "customXmlMoveToRangeEnd",
    }
)  # fmt: skip
SKIPPED_IN_RUN = frozenset(
    {
        "rPr", "lastRenderedPageBreak", "fldData", "softHyphen", "annotationRef",
        "separator", "continuationSeparator", "footnoteRef", "endnoteRef", "pgNum",
        "dayShort", "dayLong", "monthShort", "monthLong", "yearShort", "yearLong",
        "commentReference", "footnoteReference", "endnoteReference", "contentPart",
    }
)  # fmt: skip
SKIPPED_IN_BODY = frozenset(
    {
        "sectPr", "bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd",
        "commentRangeStart", "commentRangeEnd", "tblPr", "tblGrid", "trPr", "tcPr",
        "tblPrEx", "sdtPr", "sdtEndPr", "moveFromRangeStart", "moveFromRangeEnd",
        "moveToRangeStart", "moveToRangeEnd", "customXmlPr",
    }
)  # fmt: skip


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def value(element: Element | None, name: str = "val") -> str | None:
    return None if element is None else element.get(W + name)


def switched_on(element: Element | None) -> bool | None:
    """A Word on/off property: absent, or on unless its value says off."""
    if element is None:
        return None
    return value(element) not in OFF


def unpack(data: bytes) -> zipfile.ZipFile:
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise UnreadablePolicy("This is not a Word file: it is not a .docx package.") from error
    parts = package.infolist()
    if len(parts) > MAX_PARTS:
        raise UnreadablePolicy("This Word file holds too many parts to be a document.")
    if sum(part.file_size for part in parts) > MAX_TOTAL_BYTES:
        raise UnreadablePolicy("This Word file unpacks to more than 256 MB.")
    return package


def read_part(package: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        with package.open(name) as part:
            content = part.read(MAX_PART_BYTES + 1)
    except KeyError:
        return None
    except (zipfile.BadZipFile, OSError, EOFError) as error:
        raise UnreadablePolicy(f"Part of this Word file is damaged ({name}).") from error
    if len(content) > MAX_PART_BYTES:
        raise UnreadablePolicy(f"Part of this Word file is larger than 64 MB ({name}).")
    return content


def parse_xml(content: bytes, name: str) -> Element:
    """Parse one part, refusing a DTD, which no Word part declares and an attack would."""
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = content.decode("utf-16")
        text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
        markup: str | bytes = text
        declares = "<!DOCTYPE" in text or "<!ENTITY" in text
    else:
        markup = content
        declares = b"<!DOCTYPE" in content or b"<!ENTITY" in content
    if declares:
        raise UnreadablePolicy(f"This Word file's {name} declares a DTD, which Word never does.")
    try:
        return ElementTree.fromstring(markup)
    except ElementTree.ParseError as error:
        raise UnreadablePolicy(
            f"Part of this Word file is not well-formed XML ({name})."
        ) from error


def relationships(package: zipfile.ZipFile, part: str) -> dict[str, str]:
    """The targets a part points to, by relationship type, as package paths."""
    folder = dirname(part)
    rels = read_part(package, join(folder, "_rels", part.rsplit("/", 1)[-1] + ".rels"))
    found: dict[str, str] = {}
    if rels is None:
        return found
    for relationship in parse_xml(rels, "relationships").iter(RELS + "Relationship"):
        if relationship.get("TargetMode") == "External":
            continue
        target = relationship.get("Target", "")
        path = target.lstrip("/") if target.startswith("/") else normpath(join(folder, target))
        found.setdefault(relationship.get("Type", "").rsplit("/", 1)[-1], path)
    return found


@dataclass(frozen=True)
class RunLook:
    bold: bool | None = None
    bold_cs: bool | None = None
    size: float | None = None
    size_cs: float | None = None
    capitals: bool | None = None
    hidden: bool | None = None

    def over(self, other: RunLook) -> RunLook:
        """This look, with anything it leaves unsaid taken from the other."""
        return RunLook(
            bold=self.bold if self.bold is not None else other.bold,
            bold_cs=self.bold_cs if self.bold_cs is not None else other.bold_cs,
            size=self.size if self.size is not None else other.size,
            size_cs=self.size_cs if self.size_cs is not None else other.size_cs,
            capitals=self.capitals if self.capitals is not None else other.capitals,
            hidden=self.hidden if self.hidden is not None else other.hidden,
        )


def run_look(rpr: Element | None) -> RunLook:
    if rpr is None:
        return RunLook()

    def half_points(tag: str) -> float | None:
        found = value(rpr.find(W + tag))
        return int(found) / 2 if found is not None and found.isdigit() else None

    return RunLook(
        bold=switched_on(rpr.find(W + "b")),
        bold_cs=switched_on(rpr.find(W + "bCs")),
        size=half_points("sz"),
        size_cs=half_points("szCs"),
        capitals=switched_on(rpr.find(W + "caps")),
        hidden=switched_on(rpr.find(W + "vanish")),
    )


@dataclass(frozen=True)
class ParagraphLook:
    alignment: str | None = None
    outline: int | None = None
    num_id: str | None = None
    level: int | None = None

    def over(self, other: ParagraphLook) -> ParagraphLook:
        return ParagraphLook(
            alignment=self.alignment if self.alignment is not None else other.alignment,
            outline=self.outline if self.outline is not None else other.outline,
            num_id=self.num_id if self.num_id is not None else other.num_id,
            level=self.level if self.level is not None else other.level,
        )


def paragraph_look(ppr: Element | None) -> ParagraphLook:
    if ppr is None:
        return ParagraphLook()
    outline = value(ppr.find(W + "outlineLvl"))
    numbering = ppr.find(W + "numPr")
    num_id = level = None
    if numbering is not None:
        num_id = value(numbering.find(W + "numId"))
        found = value(numbering.find(W + "ilvl"))
        level = int(found) if found is not None and found.isdigit() else None
    return ParagraphLook(
        alignment=value(ppr.find(W + "jc")),
        outline=int(outline) if outline is not None and outline.isdigit() else None,
        num_id=num_id,
        level=level,
    )


@dataclass(frozen=True)
class Style:
    name: str
    based_on: str | None
    run: RunLook
    paragraph: ParagraphLook


class StyleSheet:
    """A file's styles, each resolved through the styles it is based on."""

    def __init__(self, root: Element | None) -> None:
        self.styles: dict[str, Style] = {}
        self.default_paragraph: str | None = None
        self.default_run = RunLook()
        self.default_paragraph_look = ParagraphLook()
        if root is None:
            return
        defaults = root.find(W + "docDefaults")
        if defaults is not None:
            self.default_run = run_look(defaults.find(f"{W}rPrDefault/{W}rPr"))
            self.default_paragraph_look = paragraph_look(defaults.find(f"{W}pPrDefault/{W}pPr"))
        for style in root.findall(W + "style"):
            identifier = style.get(W + "styleId")
            if identifier is None:
                continue
            self.styles[identifier] = Style(
                name=value(style.find(W + "name")) or identifier,
                based_on=value(style.find(W + "basedOn")),
                run=run_look(style.find(W + "rPr")),
                paragraph=paragraph_look(style.find(W + "pPr")),
            )
            default = style.get(W + "default") in ("1", "true", "on")
            if default and style.get(W + "type") == "paragraph":
                self.default_paragraph = identifier

    def chain(self, identifier: str | None) -> list[Style]:
        """The style and those it is based on, nearest first."""
        found: list[Style] = []
        seen: set[str] = set()
        while identifier and identifier in self.styles and identifier not in seen:
            seen.add(identifier)
            found.append(self.styles[identifier])
            identifier = self.styles[identifier].based_on
        return found

    def name(self, identifier: str | None) -> str | None:
        return self.styles[identifier].name if identifier in self.styles else None

    def run(self, paragraph_style: str | None, run_style: str | None, direct: RunLook) -> RunLook:
        look = direct
        for style in self.chain(run_style):
            look = look.over(style.run)
        for style in self.chain(paragraph_style):
            look = look.over(style.run)
        return look.over(self.default_run)

    def paragraph(self, style: str | None, direct: ParagraphLook) -> ParagraphLook:
        look = direct
        for each in self.chain(style):
            look = look.over(each.paragraph)
        return look.over(self.default_paragraph_look)

    def numbering_style(self, identifier: str) -> str | None:
        """The list a numbering style stands for, which definitions linked to it use."""
        for style in self.chain(identifier):
            if style.paragraph.num_id is not None:
                return style.paragraph.num_id
        return None


@dataclass
class Piece:
    text: str
    look: RunLook


@dataclass
class Gathered:
    """What one paragraph's runs hold, gathered while walking them."""

    pieces: list[Piece] = field(default_factory=list)
    boxes: list[Element] = field(default_factory=list)
    contents: bool = False


@dataclass
class Field:
    code: str = ""
    """What the field computes, such as "TOC" for a contents page, read before its result."""


class Reader:
    def __init__(self, styles: StyleSheet, numbering: Numbering) -> None:
        self.styles = styles
        self.numbering = numbering
        self.position = 0
        self.fields: list[Field] = []
        self.taken = 0
        self.unread: Counter[str] = Counter()
        self.revisions = 0
        self.hidden = 0

    def blocks(self, parent: Element, place: Place) -> list[Item]:
        items: list[Item] = []
        for child in parent:
            tag = local(child.tag)
            if tag == "p":
                items.extend(self.paragraph(child, place))
            elif tag == "tbl":
                items.append(self.table(child, place))
            elif tag == "sdt":
                gallery = child.find(f"{W}sdtPr/{W}docPartObj/{W}docPartGallery")
                inner: Place = "contents" if value(gallery) == "Table of Contents" else place
                content = child.find(W + "sdtContent")
                if content is not None:
                    items.extend(self.blocks(content, inner))
            elif tag in ("customXml", "ins", "moveTo", "smartTag"):
                self.revisions += tag in ("ins", "moveTo")
                items.extend(self.blocks(child, place))
            elif tag in ("del", "moveFrom"):
                self.revisions += 1
            elif tag == "AlternateContent":
                choice = child.find(MC + "Choice")
                if choice is not None:
                    items.extend(self.blocks(choice, place))
            elif tag not in SKIPPED_IN_BODY:
                self.not_taken(child, tag)
        return items

    def table(self, element: Element, place: Place) -> Table:
        position = self.position
        rows: list[Row] = []
        for row in wrapped(element, "tr"):
            header = switched_on(row.find(f"{W}trPr/{W}tblHeader")) is True
            cells: list[tuple[Paragraph, ...]] = []
            for cell in wrapped(row, "tc"):
                inner: Place = place if place in ("contents", "text box") else "cell"
                found = self.blocks(cell, inner)
                paragraphs: list[Paragraph] = []
                for item in found:
                    paragraphs.extend(item.paragraphs() if isinstance(item, Table) else [item])
                cells.append(tuple(paragraphs))
            rows.append(Row(cells=tuple(cells), header=header))
        return Table(position=position, rows=tuple(rows))

    def paragraph(self, element: Element, place: Place) -> list[Item]:
        properties = element.find(W + "pPr")
        style = value(properties.find(W + "pStyle")) if properties is not None else None
        style = style or self.styles.default_paragraph
        look = self.styles.paragraph(style, paragraph_look(properties))
        gathered = Gathered()
        self.inline(element, gathered, style, deleted=False)
        position = self.position
        self.position += 1
        text = "".join(piece.text for piece in gathered.pieces).translate(LIGATURES)

        number: Number | None = None
        if look.num_id is not None and look.num_id != "0":
            level = look.level
            if level is None:
                level = self.numbering.level_for_style(look.num_id, style)
            number = self.numbering.number(look.num_id, level)

        name = self.styles.name(style) or ""
        heading = HEADING_STYLE.match(name)
        heading_level = int(heading.group(1)) if heading else None
        if heading_level is None and look.outline is not None and look.outline < 9:
            heading_level = look.outline + 1
        contents = gathered.contents or name.lower().startswith("toc ") or name == "TOC Heading"
        visible = [piece for piece in gathered.pieces if piece.text.strip()]
        sizes = [self.size(piece) for piece in visible]
        paragraph = Paragraph(
            position=position,
            text=text,
            place="contents" if contents else place,
            style=name or None,
            heading_level=heading_level,
            title=name.lower() == "title",
            number=number,
            bold=bool(visible) and all(self.bold(piece) for piece in visible),
            size=max((size for size in sizes if size is not None), default=None),
            centred=look.alignment == "center",
            capitals=in_capitals(text, visible),
        )
        items: list[Item] = [paragraph]
        for box in gathered.boxes:
            items.extend(self.blocks(box, "text box"))
        return items

    @staticmethod
    def bold(piece: Piece) -> bool:
        if ARABIC.search(piece.text):
            return bool(piece.look.bold_cs)
        return bool(piece.look.bold)

    @staticmethod
    def size(piece: Piece) -> float | None:
        if ARABIC.search(piece.text):
            return piece.look.size_cs or piece.look.size
        return piece.look.size

    def inline(self, parent: Element, gathered: Gathered, style: str | None, deleted: bool) -> None:
        for child in parent:
            tag = local(child.tag)
            if tag == "r":
                self.run(child, gathered, style, deleted)
            elif tag in ("del", "moveFrom"):
                self.revisions += 1
                self.inline(child, gathered, style, deleted=True)
            elif tag in ("ins", "moveTo"):
                self.revisions += 1
                self.inline(child, gathered, style, deleted)
            elif tag in ("hyperlink", "smartTag", "customXml", "fldSimple", "dir", "bdo"):
                self.inline(child, gathered, style, deleted)
            elif tag == "sdt":
                content = child.find(W + "sdtContent")
                if content is not None:
                    self.inline(content, gathered, style, deleted)
            elif tag == "AlternateContent":
                choice = child.find(MC + "Choice")
                if choice is not None:
                    self.inline(choice, gathered, style, deleted)
            elif tag not in SKIPPED_IN_PARAGRAPH:
                self.not_taken(child, tag)

    def run(self, element: Element, gathered: Gathered, style: str | None, deleted: bool) -> None:
        direct = element.find(W + "rPr")
        run_style = value(direct.find(W + "rStyle")) if direct is not None else None
        look = self.styles.run(style, run_style, run_look(direct))
        for child in element:
            tag = local(child.tag)
            if tag == "fldChar":
                self.field(child)
            elif tag == "instrText":
                if self.fields:
                    self.fields[-1].code += child.text or ""
            elif tag == "delText":
                continue
            elif tag in ("t", "tab", "ptab", "br", "cr", "noBreakHyphen", "sym"):
                if deleted:
                    if tag == "t":
                        self.revisions += 1
                    continue
                text = self.character(child, tag)
                if tag == "t":
                    self.taken += len(text)
                    if look.hidden:
                        self.hidden += len(text)
                if any(f.code.split()[:1] in (["TOC"], ["PAGEREF"]) for f in self.fields):
                    gathered.contents = True
                gathered.pieces.append(Piece(text, look))
            elif tag in ("drawing", "pict", "object", "AlternateContent"):
                gathered.boxes.extend(self.text_boxes(child))
            elif tag not in SKIPPED_IN_RUN:
                self.not_taken(child, tag)

    @staticmethod
    def character(element: Element, tag: str) -> str:
        match tag:
            case "t":
                return element.text or ""
            case "tab" | "ptab":
                return "\t"
            case "br":
                return "" if value(element, "type") in ("page", "column") else "\n"
            case "cr":
                return "\n"
            case "noBreakHyphen":
                return "-"
            case _:
                code = value(element, "char") or ""
                try:
                    return chr(int(code, 16))
                except ValueError:
                    return ""

    def field(self, element: Element) -> None:
        """Fields nest: each begins, shows its result, and ends, innermost first."""
        kind = value(element, "fldCharType")
        if kind == "begin":
            self.fields.append(Field())
        elif kind == "end" and self.fields:
            self.fields.pop()

    @staticmethod
    def text_boxes(element: Element) -> list[Element]:
        """The text boxes inside a drawing, each once: a fallback repeats its choice."""
        fallbacks = {id(inner) for f in element.iter(MC + "Fallback") for inner in f.iter()}
        return [box for box in element.iter(W + "txbxContent") if id(box) not in fallbacks]

    def not_taken(self, element: Element, tag: str) -> None:
        """An element this does not read: harmless unless it held text, which is then missed."""
        if any(text.text for text in element.iter(W + "t")):
            self.unread[tag] += 1


def wrapped(parent: Element, tag: str) -> list[Element]:
    """A table's rows or a row's cells, including any wrapped in a content control."""
    found: list[Element] = []
    for child in parent:
        kind = local(child.tag)
        if kind == tag:
            found.append(child)
        elif kind in ("sdt", "customXml"):
            inner = child.find(W + "sdtContent") if kind == "sdt" else child
            if inner is not None:
                found.extend(wrapped(inner, tag))
    return found


def in_capitals(text: str, pieces: list[Piece]) -> bool:
    """Set in capitals, by the property or by the letters, when its letters have a case."""
    letters = [character for character in text if character.isalpha()]
    cased = [character for character in letters if character.isupper() or character.islower()]
    if not cased or len(cased) * 2 < len(letters):
        return False
    return all(piece.look.capitals for piece in pieces) or not any(c.islower() for c in cased)


def count_text(root: Element) -> int:
    """Characters in every text element of the part, counted without the reader's walk.

    Deleted text is held in other elements and is not counted; a fallback repeats its
    choice's content, so only the choice is.
    """
    fallbacks = {id(inner) for f in root.iter(MC + "Fallback") for inner in f.iter()}
    deleted = {
        id(inner)
        for tag in ("del", "moveFrom")
        for marked in root.iter(W + tag)
        for inner in marked.iter()
    }
    return sum(
        len(text.text or "")
        for text in root.iter(W + "t")
        if id(text) not in fallbacks and id(text) not in deleted
    )


def counted(count: int, noun: str) -> str:
    return f"{count} {noun} was" if count == 1 else f"{count} {noun}s were"


def read_docx(data: bytes) -> ReadFile:
    """Read a Word file into paragraphs and tables, with whatever a reviewer should know."""
    package = unpack(data)
    main = relationships(package, "").get("officeDocument", "word/document.xml")
    content = read_part(package, main)
    if content is None:
        raise UnreadablePolicy("This is not a Word document: it has no document part.")
    document = parse_xml(content, "document")
    body = document.find(W + "body")
    if body is None:
        raise UnreadablePolicy("This Word document has no body.")
    parts = relationships(package, main)

    def part(kind: str) -> Element | None:
        found = read_part(package, parts[kind]) if kind in parts else None
        return parse_xml(found, kind) if found is not None else None

    styles = StyleSheet(part("styles"))
    numbering = Numbering(part("numbering"), styles.numbering_style)
    reader = Reader(styles, numbering)
    items = reader.blocks(body, "body")

    notices: list[str] = []
    if reader.revisions:
        notices.append("This file has tracked changes, read as if every change were accepted.")
    comments = part("comments")
    if comments is not None and (count := len(comments.findall(W + "comment"))):
        notices.append(f"This file's {counted(count, 'comment')} not read.")
    notes = part("footnotes")
    if notes is not None:
        written = [
            note
            for note in notes.findall(W + "footnote")
            if note.get(W + "type") is None and "".join(note.itertext()).strip()
        ]
        if written:
            notices.append(f"This file's {counted(len(written), 'footnote')} not read.")
    if reader.hidden:
        notices.append(f"This file has {reader.hidden} characters of hidden text, read as shown.")
    for form in sorted(numbering.undrawn):
        notices.append(f"Numbers in Word's {form} format are shown as 1, 2, 3.")

    return ReadFile(
        format="docx",
        items=tuple(items),
        missed=max(0, count_text(body) - reader.taken),
        unread=tuple(sorted(reader.unread)),
        notices=tuple(notices),
    )
