"""Finding the clauses a text points at.

DPOLens links what a document states, and nothing else. A reference exists
because the text writes it, so the link can be checked by reading the sentence
it came from.

Extraction is per numbering tradition, because a law writes "Article 6(1)(f)"
and a policy writes "Section 4.2". Resolution then checks the target against the
keys the document actually has. A reference that resolves becomes a link; one
that does not becomes a flag, never a silent drop, because it usually means the
document points at something that is not there.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    """A pointer from one clause to another, with the wording that produced it."""

    target_key: str
    raw_text: str


@dataclass(frozen=True)
class Resolution:
    resolved: tuple[Reference, ...]
    unresolved: tuple[Reference, ...]


ANOTHER_INSTRUMENT = re.compile(
    r"\s+of\s+(?:the\s+)?(Directive|Regulation|Decision|Treaty|Charter|Convention|Protocol)\b"
)
"""'Article 25(6) of Directive 95/46/EC' is a reference to a different law."""


def _points_elsewhere(text: str, end: int) -> bool:
    return ANOTHER_INSTRUMENT.match(text, end) is not None


def _eu_law(text: str, document_slug: str) -> list[Reference]:
    """Article 6(1)(f), and point (a) of Article 9(2).

    A reference that names another instrument is left alone. Linking it inside
    this law would be worse than not linking it at all, because the link would
    look authoritative and point at the wrong clause.
    """
    found: dict[str, str] = {}

    with_point = re.compile(r"point \(([0-9a-z]+)\) of Article (\d+)\((\d+)\)", re.IGNORECASE)
    for match in with_point.finditer(text):
        if _points_elsewhere(text, match.end()):
            continue
        point, article, paragraph = match.groups()
        key = f"{document_slug}:art-{article}:para-{paragraph}:pt-{point.lower()}"
        found.setdefault(key, match.group(0))

    plain = re.compile(r"Article (\d+)\((\d+)\)(?:\(([0-9a-z]+)\))?")
    for match in plain.finditer(text):
        if _points_elsewhere(text, match.end()):
            continue
        article, paragraph, point = match.groups()
        key = f"{document_slug}:art-{article}:para-{paragraph}"
        if point:
            key = f"{key}:pt-{point.lower()}"
        found.setdefault(key, match.group(0))

    return [Reference(target_key=key, raw_text=raw) for key, raw in sorted(found.items())]


TRADITIONS = {"eu_law": _eu_law}
"""Numbering traditions. Uploaded policies add their own when they arrive."""


def extract(text: str, document_slug: str, tradition: str = "eu_law") -> list[Reference]:
    reader = TRADITIONS.get(tradition)
    if reader is None:
        raise ValueError(
            f"unknown numbering tradition {tradition!r}: expected one of {sorted(TRADITIONS)}"
        )
    return reader(text, document_slug)


def resolve(references: Iterable[Reference], known_keys: Iterable[str]) -> Resolution:
    """Split references into those that point at a real clause and those that do not."""
    keys = set(known_keys)
    resolved = tuple(reference for reference in references if reference.target_key in keys)
    unresolved = tuple(reference for reference in references if reference.target_key not in keys)
    return Resolution(resolved=resolved, unresolved=unresolved)
