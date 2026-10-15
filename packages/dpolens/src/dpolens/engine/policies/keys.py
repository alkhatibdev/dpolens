"""A clause's key: the document's own numbers first, then its headings' words, then position.

A key is the document's slug and one segment per level, joined with colons, as a pack's are.
A number that already contains its parent's ("3.5.1" under "3.5") stands alone, so the key is
"petroc:3.5.1" rather than "petroc:3:3.5:3.5.1". A heading with no number gives its first
words, Arabic letters kept, and a paragraph with neither gives its place among its parent's,
"p1", "p2". The parser proposes keys; the reviewer can change any of them.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from dpolens.engine.policies.patterns import ARABIC_DIGITS, DIACRITICS, segment
from dpolens.engine.policies.structure import Node
from dpolens.engine.policies.tree import Clause
from dpolens.engine.search.language import language_of

HEADING_WORDS_IN_KEY = 6


def heading_words(heading: str) -> str:
    """A heading as a key segment: its first words, lower case, joined with hyphens."""
    text = unicodedata.normalize("NFKC", heading).translate(ARABIC_DIGITS)
    text = DIACRITICS.sub("", text).lower()
    found = re.findall(r"\w+", text)
    return "-".join(found[:HEADING_WORDS_IN_KEY]).strip("_")


def slug_of(name: str) -> str:
    """A document's slug from its file name or title: ASCII where it can be, as packs' are."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(character for character in text if not unicodedata.combining(character))
    found = re.findall(r"\w+", text.lower())
    return "-".join(found)[:60].strip("-_") or "policy"


def contains(segment_: str, parent: str) -> bool:
    """Whether a number continues its parent's, as "3.5.1" continues "3.5"."""
    return segment_.startswith((parent + ".", parent + "-")) and parent[:1].isdigit()


def assign(slug: str, roots: list[Node]) -> tuple[Clause, ...]:
    return tuple(_assign(slug, [], roots))


def _assign(slug: str, path: list[str], nodes: list[Node]) -> list[Clause]:
    taken: Counter[str] = Counter()
    unnamed = 0
    clauses: list[Clause] = []
    for node in nodes:
        if node.label is not None and segment(node.label):
            own = segment(node.label)
        elif node.heading:
            own = heading_words(node.heading) or ""
        else:
            own = ""
        if not own:
            unnamed += 1
            own = f"p{unnamed}"
        taken[own] += 1
        if taken[own] > 1:
            # A second "1-1" is a numbering slip the checks flag; "_2" cannot be a real number.
            own = f"{own}_{taken[own]}" if any(c.isdigit() for c in own) else f"{own}-{taken[own]}"
        if path and node.label is not None and contains(own, path[-1]):
            here = [*path[:-1], own]
        else:
            here = [*path, own]
        text = "\n".join(line for line in node.lines if line.strip())
        clauses.append(
            Clause(
                key=":".join([slug, *here]),
                kind=node.kind,
                layer=node.layer,
                label=node.label,
                heading=node.heading,
                text=text,
                lang=language_of(" ".join(filter(None, [node.heading, text]))),
                positions=tuple(node.positions),
                children=tuple(_assign(slug, here, node.children)),
            )
        )
    return clauses
