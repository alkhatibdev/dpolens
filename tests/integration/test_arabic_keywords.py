"""Keyword search over Arabic text, and the light normalisation it goes through."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.packs.load import load_pack
from dpolens.engine.search import ALTERNATIVES, keyword_search

pytestmark = pytest.mark.integration


@pytest.fixture
def loaded(session: Session, bilingual_pack: Path) -> Session:
    load_pack(session, bilingual_pack)
    session.commit()
    return session


def light(session: Session, words: str) -> str:
    return str(session.execute(text("SELECT arabic_light(:words)"), {"words": words}).scalar())


@pytest.mark.parametrize(
    ("written", "indexed"),
    [
        # The article comes off, alone or after a conjunction or preposition.
        ("البيانات الشخصية", "بيانات شخصيه"),
        ("والمعالجة للمعالجة بالنسبة كالتالي", "معالجه معالجه نسبه تالي"),
        # Spellings that change no word become one spelling.
        ("إذا أي آخر", "اذا اي اخر"),
        ("مسؤول مسئول", "مسءول مسءول"),
        ("مُعالَجةُ مســـؤول", "معالجه مسءول"),
        ("المادة (٢٢)", "ماده 22"),
        # A word too short to have an article keeps its letters.
        ("الى بالغ", "الي بالغ"),
        # English words pass through, since developers mix them in.
        ("هل نحتاج DPO؟", "هل نحتاج DPO"),
    ],
)
def test_light_normalisation(session: Session, written: str, indexed: str) -> None:
    assert light(session, written) == indexed


def test_an_arabic_question_finds_the_word_with_or_without_its_article(loaded: Session) -> None:
    """بيانات in a question, البيانات in the law: the case the folding exists for."""
    found = [candidate.key for candidate in keyword_search(loaded, "بيانات", lang="ar")]

    assert "bilingual:art-2:para-1:pt-a" in found


def test_the_snowball_index_stems_the_two_forms_apart(loaded: Session) -> None:
    """Postgres's stemmer cuts بيانات to يانا and البيانات to بيان, which never meet."""
    found = [
        candidate.key
        for candidate in keyword_search(
            loaded, "بيانات", lang="ar", indexes=ALTERNATIVES["snowball"]
        )
    ]

    assert "bilingual:art-2:para-1:pt-a" not in found


def test_folding_before_the_stemmer_brings_the_two_forms_back_together(
    loaded: Session,
) -> None:
    found = [
        candidate.key
        for candidate in keyword_search(
            loaded, "بيانات", lang="ar", indexes=ALTERNATIVES["folded-snowball"]
        )
    ]

    assert "bilingual:art-2:para-1:pt-a" in found


def test_the_default_stems_where_the_folding_alone_does_not(loaded: Session) -> None:
    """ضروري in a question, ضرورية in the law: one stem, and two words to the folding alone."""
    stemmed = [candidate.key for candidate in keyword_search(loaded, "ضروري", lang="ar")]
    folded = [
        candidate.key
        for candidate in keyword_search(loaded, "ضروري", lang="ar", indexes=ALTERNATIVES["light"])
    ]

    assert "bilingual:art-2:para-1:pt-b" in stemmed
    assert "bilingual:art-2:para-1:pt-b" not in folded


def test_arabic_search_reads_only_arabic_text(loaded: Session) -> None:
    found = keyword_search(loaded, "بيانات DPO data", lang="ar")

    assert found
    assert {candidate.lang for candidate in found} == {"ar"}


def test_a_question_with_no_words_finds_nothing_rather_than_failing(loaded: Session) -> None:
    assert keyword_search(loaded, "؟!", lang="ar") == []
