"""A citation says when the clause in hand is a translation, and which text prevails.

An assistant quotes what it is given. Handed an English translation without
being told the Arabic prevails, it would cite the translation as the law.
"""

from __future__ import annotations

from datetime import date

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


def test_a_translation_carries_the_text_that_prevails() -> None:
    translated = {
        **ARTICLE,
        "is_authoritative": False,
        "authoritative_language": "ar",
        "authoritative_text": "إذا وافق صاحب البيانات.",
    }

    assert Clause.of(translated).prevailing_text == "إذا وافق صاحب البيانات."
    assert Clause.of({**ARTICLE, "authoritative_language": "en"}).prevailing_text is None


def test_a_citation_says_when_a_provision_starts_later() -> None:
    later = {**ARTICLE, "in_force": False, "in_force_from": "2027-05-13"}

    assert Clause.of(later, as_of=date(2026, 11, 5)).citation.endswith(
        "version 2020/1, in force from 2027-05-13"
    )


def test_a_citation_says_when_no_day_is_set() -> None:
    pending = {**ARTICLE, "in_force": False, "in_force_from": None}

    assert Clause.of(pending).citation.endswith("version 2020/1, not in force yet: no date set")


def test_a_citation_says_when_a_provision_ends() -> None:
    ending = {**ARTICLE, "in_force_until": "2027-05-13"}
    ended = {**ending, "in_force": False}

    assert Clause.of(ending).citation.endswith("in force since 2020-01-01, until 2027-05-13")
    assert Clause.of(ended, as_of=date(2027, 6, 1)).citation.endswith(
        "no longer in force since 2027-05-13"
    )


def test_the_words_an_amendment_brings_come_with_the_clause() -> None:
    amended = {
        **ARTICLE,
        "coming": {
            "heading": None,
            "text": "Personal data shall be kept no longer than twelve months.",
            "in_force_from": "2027-01-17",
            "dates_set_by": "Act No. 56 of 2026",
        },
    }

    coming = Clause.of(amended).coming

    assert coming is not None
    assert (coming.in_force_from, coming.set_by) == ("2027-01-17", "Act No. 56 of 2026")


def test_an_instance_that_sends_no_days_reads_as_in_force_since_its_version() -> None:
    older = {
        name: value
        for name, value in ARTICLE.items()
        if name not in ("in_force", "in_force_from", "in_force_until", "dates_set_by", "coming")
    }

    clause = Clause.of(older)

    assert (clause.in_force, clause.in_force_from) == (True, "2020-01-01")
    assert clause.citation.endswith("in force since 2020-01-01")
