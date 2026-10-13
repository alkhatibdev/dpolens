"""Which language a question is in, read from the letters it is written in.

A question in Arabic letters is searched as Arabic and any other as English,
since those are the languages with an index. The letters decide, not a model,
because they cannot be mistaken about which alphabet was typed. A question that
mixes the two goes by whichever has more letters, so "هل نحتاج DPO؟" is Arabic.
"""

from __future__ import annotations

import re

ARABIC_LETTER = re.compile(r"[ء-يٱ-ۓۺ-ۿ]")
LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")


def language_of(question: str) -> str:
    arabic = len(ARABIC_LETTER.findall(question))
    latin = len(LATIN_LETTER.findall(question))
    return "ar" if arabic > latin else "en"
