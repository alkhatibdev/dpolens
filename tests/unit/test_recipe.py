"""The string that gets embedded.

A clause alone often carries none of the meaning a question is phrased in.
Article 17(1)(b) reads "the data subject withdraws consent on which the
processing is based", which no question about deleting an account will match.
The recipe puts the headings above it in front.
"""

from __future__ import annotations

from dpolens.engine.embedding.recipe import MAX_TOKENS, RecipeInput, build


def words(text: str) -> int:
    """A stand-in tokeniser, so these tests need no model."""
    return len(text.split())


def test_the_clause_is_placed_by_its_ancestry() -> None:
    result = build(
        RecipeInput(
            document_short_name="GDPR",
            ancestor_headings=["Right to erasure", "1."],
            text="the data subject withdraws consent",
        ),
        words,
    )

    assert result == "GDPR > Right to erasure > 1. > the data subject withdraws consent"


def test_a_clause_with_no_ancestry_keeps_the_document_name() -> None:
    result = build(
        RecipeInput(document_short_name="GDPR", ancestor_headings=[], text="Article text."),
        words,
    )

    assert result == "GDPR > Article text."


def test_empty_headings_are_dropped() -> None:
    result = build(
        RecipeInput(
            document_short_name="GDPR",
            ancestor_headings=["", "  ", "Right to erasure"],
            text="the text",
        ),
        words,
    )

    assert result == "GDPR > Right to erasure > the text"


def test_a_long_prefix_loses_its_middle_not_its_ends() -> None:
    """The document name places the clause and the nearest heading carries the
    most meaning, so the levels between them are what can go."""
    headings = [f"Heading number {number} of many words here" for number in range(1, 12)]

    result = build(
        RecipeInput(document_short_name="GDPR", ancestor_headings=headings, text="the text"),
        words,
    )
    prefix = result.split(" > the text")[0]

    assert prefix.startswith("GDPR")
    assert prefix.endswith(headings[-1])
    assert words(prefix) <= MAX_TOKENS


def test_the_text_itself_is_never_truncated_by_the_recipe() -> None:
    """The cap applies to the prefix. Truncating the clause would change what a
    citation quotes."""
    long_text = " ".join(f"word{number}" for number in range(200))

    result = build(
        RecipeInput(document_short_name="GDPR", ancestor_headings=["A"], text=long_text),
        words,
    )

    assert result.endswith(long_text)
