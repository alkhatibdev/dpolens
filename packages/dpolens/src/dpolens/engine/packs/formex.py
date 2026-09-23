"""Converting Formex XML into clauses.

Formex is the format the Publications Office uses for EU law, so the structure
is already decided by the publisher and this module only translates it. Nothing
here guesses: an element that is not recognised raises rather than being dropped
quietly, because a clause lost here would be missing from every search.

Footnotes are left out of clause text on purpose. They are publishing apparatus,
citing the Official Journal, and they are not part of the provision a citation
quotes.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from xml.etree import ElementTree

from dpolens.engine.packs.format import Clause

SKIPPED_TAGS = frozenset({"NOTE"})
PARAGRAPH_NUMBER = re.compile(r"(\d+)")
POINT_LABEL = re.compile(r"\(?([0-9a-z]+)\)?", re.IGNORECASE)


class FormexError(Exception):
    """The source file was not shaped the way the converter expects."""


def _quote_char(element: ElementTree.Element) -> str:
    """QUOT.START and QUOT.END carry the code point of the quotation mark."""
    code = element.get("CODE")
    if not code:
        return '"'
    return chr(int(code, 16))


def text_of(element: ElementTree.Element) -> str:
    """The readable text of an element, without footnotes or markup."""
    parts: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        for child in node:
            if child.tag in SKIPPED_TAGS:
                if child.tail:
                    parts.append(child.tail)
                continue
            if child.tag in ("QUOT.START", "QUOT.END"):
                parts.append(_quote_char(child))
            else:
                if child.text:
                    parts.append(child.text)
                walk(child)
            if child.tail:
                parts.append(child.tail)

    if element.text:
        parts.append(element.text)
    walk(element)
    return _tidy("".join(parts))


def _tidy(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _segment(prefix: str, label: str, fallback: int) -> str:
    match = POINT_LABEL.search(label)
    value = match.group(1).lower() if match else str(fallback)
    return f"{prefix}-{value}"


def parse_articles(path: Path, document_slug: str, lang: str = "en") -> list[Clause]:
    """Read every article of an act, with its paragraphs and points."""
    root = ElementTree.parse(path).getroot()
    articles = [_article(element, document_slug, lang) for element in root.iter("ARTICLE")]
    if not articles:
        raise FormexError(f"{path}: no ARTICLE elements found. Is this the act file?")
    return articles


def _article(element: ElementTree.Element, document_slug: str, lang: str) -> Clause:
    title_element = element.find("TI.ART")
    if title_element is None:
        raise FormexError("an ARTICLE has no TI.ART, so its number cannot be read")

    number_match = PARAGRAPH_NUMBER.search(text_of(title_element))
    if number_match is None:
        raise FormexError(f"cannot read an article number from {text_of(title_element)!r}")

    key = f"{document_slug}:art-{number_match.group(1)}"
    subtitle = element.find("STI.ART")

    paragraphs = element.findall("PARAG")
    if paragraphs:
        own_text = ""
        children = tuple(
            _paragraph(paragraph, key, lang, order) for order, paragraph in enumerate(paragraphs, 1)
        )
    else:
        # Some articles have no numbered paragraphs, among them Article 4, whose
        # definitions are a list of points directly under the article.
        blocks = [_alinea(alinea, key, lang) for alinea in element.findall("ALINEA")]
        own_text = "\n\n".join(text for text, _ in blocks if text)
        children = tuple(child for _, points in blocks for child in points)

    return Clause(
        key=key,
        clause_type="article",
        label=text_of(title_element),
        heading=text_of(subtitle) if subtitle is not None else None,
        body_text=own_text,
        lang=lang,
        normative=True,
        children=children,
    )


def _paragraph(element: ElementTree.Element, parent_key: str, lang: str, order: int) -> Clause:
    number = element.find("NO.PARAG")
    label = text_of(number) if number is not None else f"{order}."
    key = f"{parent_key}:{_segment('para', label, order)}"

    alineas = element.findall("ALINEA")
    if not alineas:
        raise FormexError(f"{key}: a PARAG without an ALINEA has no text")

    # The first subparagraph carries the paragraph's own text and its points, so
    # that a citation keeps the shape the law uses: point (f) of Article 6(1) is
    # art-6:para-1:pt-f. Further subparagraphs are clauses of their own, which
    # is also how they are cited: the second subparagraph of Article 6(1).
    body, children = _alinea(alineas[0], key, lang)
    for order, extra in enumerate(alineas[1:], start=2):
        extra_body, extra_points = _alinea(extra, f"{key}:sub-{order}", lang)
        children = (
            *children,
            Clause(
                key=f"{key}:sub-{order}",
                clause_type="subparagraph",
                label=None,
                heading=None,
                body_text=extra_body,
                lang=lang,
                normative=True,
                children=extra_points,
            ),
        )

    return Clause(
        key=key,
        clause_type="paragraph",
        label=label,
        heading=None,
        body_text=body,
        lang=lang,
        normative=True,
        children=children,
    )


def _alinea(
    element: ElementTree.Element, parent_key: str, lang: str
) -> tuple[str, tuple[Clause, ...]]:
    """An alinea is either plain text, or a lead-in followed by a list of points."""
    lead_in_parts: list[str] = []
    children: list[Clause] = []

    if element.text and element.text.strip():
        lead_in_parts.append(_tidy(element.text))

    for child in element:
        if child.tag == "LIST":
            children.extend(_points(child, parent_key, lang))
        elif child.tag in ("QUOT.START", "QUOT.END"):
            # A quotation mark can sit directly in the alinea, around a defined
            # term such as 'accountability'.
            lead_in_parts.append(_quote_char(child))
        elif child.tag not in SKIPPED_TAGS:
            lead_in_parts.append(text_of(child))
        if child.tail and child.tail.strip():
            lead_in_parts.append(_tidy(child.tail))

    return "\n\n".join(part for part in lead_in_parts if part), tuple(children)


def _points(element: ElementTree.Element, parent_key: str, lang: str) -> list[Clause]:
    points: list[Clause] = []
    for order, item in enumerate(element.findall("ITEM"), 1):
        np = item.find("NP")
        if np is None:
            # A dash list: the item carries text and no number of its own.
            points.append(_dash_point(item, parent_key, lang, order))
            continue

        number = np.find("NO.P")
        label = text_of(number) if number is not None else f"({order})"
        key = f"{parent_key}:{_segment('pt', label, order)}"

        text_element = np.find("TXT")
        body = text_of(text_element) if text_element is not None else ""

        # A sub-list hangs off the point in a <P>, one level down. Recursion
        # handles anything deeper.
        nested = [
            child
            for nested_list in [*np.findall("LIST"), *np.findall("P/LIST")]
            for child in _points(nested_list, key, lang)
        ]

        points.append(
            Clause(
                key=key,
                clause_type="point",
                label=label,
                heading=None,
                body_text=body,
                lang=lang,
                normative=True,
                children=tuple(nested),
            )
        )
    return points


def _dash_point(item: ElementTree.Element, parent_key: str, lang: str, order: int) -> Clause:
    paragraphs = item.findall("P")
    if not paragraphs:
        raise FormexError(f"{parent_key}: a list ITEM with neither NP nor P has no text")
    return Clause(
        key=f"{parent_key}:pt-{order}",
        clause_type="point",
        label=None,
        heading=None,
        body_text="\n\n".join(text_of(paragraph) for paragraph in paragraphs),
        lang=lang,
        normative=True,
        children=(),
    )


def parse_recitals(path: Path, document_slug: str, lang: str = "en") -> list[Clause]:
    """Read the recitals of an act. They explain it without obliging anyone."""
    root = ElementTree.parse(path).getroot()
    recitals: list[Clause] = []

    for order, element in enumerate(root.iter("CONSID"), 1):
        np = element.find("NP")
        if np is None:
            raise FormexError(f"recital {order}: CONSID without an NP has no text")

        number = np.find("NO.P")
        label = text_of(number) if number is not None else f"({order})"
        text_element = np.find("TXT")

        recitals.append(
            Clause(
                key=f"{document_slug}:{_segment('rec', label, order)}",
                clause_type="recital",
                label=label,
                heading=None,
                body_text=text_of(text_element) if text_element is not None else "",
                lang=lang,
                normative=False,
                children=(),
            )
        )

    if not recitals:
        raise FormexError(
            f"{path}: no CONSID elements found. A consolidated text has an empty "
            "preamble, so recitals come from the original act"
        )
    return recitals
