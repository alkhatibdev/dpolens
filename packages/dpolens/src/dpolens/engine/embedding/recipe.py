"""Building the string that gets embedded.

GDPR Article 17(1)(b) never says "delete" or "erase". On its own it reads "the
data subject withdraws consent on which the processing is based", which no
question about deleting an account will ever match. The meaning lives in the
headings above it.

So a clause is embedded with its ancestry in front of it, and the bare text is
what gets stored and quoted. The prefix is capped, because past a certain length
the headings drown the clause they are supposed to place.

The recipe is versioned. Changing it changes every vector, which is an explicit
re-index rather than a quiet drift.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

RECIPE_VERSION = "v1"
MAX_TOKENS = 64
SEPARATOR = " > "


@dataclass(frozen=True)
class RecipeInput:
    """What the recipe needs, so it can be tested without a database."""

    document_short_name: str
    ancestor_headings: Sequence[str]
    text: str


def build(source: RecipeInput, count_tokens: Callable[[str], int]) -> str:
    """The clause text, prefixed by where it sits, capped at 64 tokens.

    When the prefix is too long, the middle is dropped rather than the end: the
    document name places the clause and the nearest heading carries the most
    meaning, so the levels in between are what can go.
    """
    headings = [
        heading.strip() for heading in source.ancestor_headings if heading and heading.strip()
    ]
    parts = [source.document_short_name, *headings]

    while len(parts) > 1 and count_tokens(SEPARATOR.join(parts)) > MAX_TOKENS:
        if len(parts) == 2:
            parts = [parts[-1]]
            break
        # Drop from the middle, keeping the document name and the nearest heading.
        parts.pop(len(parts) // 2)

    prefix = SEPARATOR.join(parts)
    return f"{prefix}{SEPARATOR}{source.text}" if prefix else source.text
