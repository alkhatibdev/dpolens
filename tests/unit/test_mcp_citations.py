"""A citation says when the clause in hand is a translation, and which text prevails.

An assistant quotes what it is given. Handed an English translation without
being told the Arabic prevails, it would cite the translation as the law.
"""

from __future__ import annotations

from dpolens_mcp.results import Clause
from dpolens_stub import ARTICLE


def test_a_clause_in_the_language_that_prevails_carries_no_note() -> None:
    clause = Clause.of({**ARTICLE, "authoritative_language": "en"})

    assert clause.prevails is None
    assert "prevails" not in clause.citation


def test_a_translation_says_which_text_prevails() -> None:
    translated = {**ARTICLE, "is_authoritative": False, "authoritative_language": "ar"}

    clause = Clause.of(translated)

    assert clause.prevails == "ar"
    assert clause.citation.endswith(
        "A translation: where the texts differ, the Arabic text prevails"
    )


def test_an_instance_that_does_not_send_the_field_reads_as_before() -> None:
    """The MCP server can be newer than the instance it talks to."""
    clause = Clause.of({**ARTICLE, "is_authoritative": False})

    assert clause.prevails is None
