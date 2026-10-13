"""A question's language comes from the letters it is written in."""

from __future__ import annotations

import pytest

from dpolens.engine.search import language_of


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("How long can we keep a user's data?", "en"),
        ("إلى متى يمكننا الاحتفاظ ببيانات المستخدم؟", "ar"),
        # Developers mix in English words, and the Arabic still decides.
        ("هل نحتاج DPO؟", "ar"),
        ("هل يمكننا استضافة بيانات عملائنا على خوادم AWS في أوروبا؟", "ar"),
        # An English question that quotes one Arabic word is still English.
        ("What does البيانات mean in the UAE law?", "en"),
        ("المادة 22", "ar"),
        # Nothing to go by, so the default.
        ("2021?", "en"),
        # Another Latin alphabet is searched as English, the index it can use.
        ("Combien de temps garder les données ?", "en"),
    ],
)
def test_the_letters_decide(question: str, language: str) -> None:
    assert language_of(question) == language
