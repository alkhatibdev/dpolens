"""Numbers written into a policy's text, and how one follows another.

The third layer reads them from the start of a paragraph. The checks read Word's automatic
numbers the same way, because a drawn "4.2." and a typed "4.2." are the same number to the
person reading the policy.

A number's style is what "a new style goes deeper, a style seen before jumps back" compares:
"1." and "(a)" are different styles, "4.1" and "4.2" are the same one. A lone "i" could be a
roman one or the letter after "h", so it carries both readings until its neighbours decide.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ABJAD = "أبجدهوزحطيكلمنسعفصقرشتثخذضظغ"
ALPHABETICAL = "أبتثجحخدذرزسشصضطظعغفقكلمنهوي"
ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50}
"""Enough for any list a policy numbers; "MD." or "Mix." is not a numeral that starts a clause."""
ORDINAL_WORDS = (
    "أول", "ثاني", "ثالث", "رابع", "خامس", "سادس", "سابع", "ثامن", "تاسع", "عاشر",
    "حادي عشر", "ثاني عشر", "ثالث عشر", "رابع عشر", "خامس عشر",
)  # fmt: skip
ENGLISH_WORDS = ("article", "section", "part", "clause", "chapter", "schedule", "appendix", "annex")
ARABIC_WORDS = ("مادة", "فصل", "باب", "بند", "قسم", "ملحق")

DIGITS = r"[0-9٠-٩۰-۹]{1,3}"
SPACE = r"[ \t ‏‎]"
AFTER = rf"(?:{SPACE}+|$)"
DIACRITICS = re.compile(r"[ً-ٰٟـ]")

NUMBERED = re.compile(rf"^(?P<label>{DIGITS}(?:\.{DIGITS})+\.?|{DIGITS}\.){AFTER}")
HYPHENATED = re.compile(rf"^(?P<label>{DIGITS}(?:-{DIGITS})+-?|{DIGITS}-){SPACE}*")
BRACKETED = re.compile(rf"^(?P<label>\((?P<inner>{DIGITS}|[a-zA-Z]{{1,4}}|[{ABJAD}])\)){AFTER}")
CLOSED = re.compile(rf"^(?P<label>(?P<inner>{DIGITS}|[a-zA-Z]{{1,4}}|[{ABJAD}])[).]){AFTER}")
ARABIC_LETTER = re.compile(rf"^(?P<label>(?P<inner>[{ABJAD}]){SPACE}?[-\u2013]){SPACE}*")
WORDED = re.compile(
    rf"^(?P<label>(?P<word>{'|'.join(ENGLISH_WORDS)}){SPACE}+"
    rf"(?P<inner>\(?(?:{DIGITS}(?:\.{DIGITS})*|[ivxl]{{1,6}}|[a-z])\)?)[.:]?){AFTER}",
    re.IGNORECASE,
)
ARABIC_WORDED = re.compile(
    rf"^(?P<label>(?:ال)?(?P<word>{'|'.join(ARABIC_WORDS)}){SPACE}*"
    rf"(?P<inner>\(?{DIGITS}\)?|(?:ال)?(?:{'|'.join(ORDINAL_WORDS)})[ةى]?)[:.\-\u2013]?){AFTER}"
)
ORDINAL = re.compile(
    rf"^(?P<label>(?P<inner>{'|'.join(ORDINAL_WORDS)})[اً]*{SPACE}*[:.\-\u2013]){SPACE}*"
)
SEPARATOR = re.compile(rf"^{SPACE}*[:\-\u2013\u2014]{SPACE}+")
BULLET = re.compile(rf"^(?P<label>[•▪◦●■□➢✓➤○·\-\u2013\u2014*o]){SPACE}+")


@dataclass(frozen=True)
class Label:
    text: str
    """As written: "4.2.", "(a)", "Article 5", "المادة (5)", "أولاً:"."""

    style: str
    """What makes two numbers the same kind: "4.1" and "4.2" share one, "4." and "(a)" do not."""

    values: tuple[int, ...]
    """Its value at each level: "4.2" is (4, 2), "(b)" is (2,), a bullet is ()."""

    others: tuple[tuple[str, tuple[int, ...]], ...] = ()
    """Other readings of the same text, such as "(i)" as a roman one or as the letter i."""

    @property
    def bullet(self) -> bool:
        return not self.values

    def readings(self) -> list[tuple[str, tuple[int, ...]]]:
        return [(self.style, self.values), *self.others]


def number(text: str) -> int:
    return int(text.translate(ARABIC_DIGITS))


def roman_value(text: str) -> int | None:
    text = text.lower()
    if not text or any(letter not in ROMAN for letter in text):
        return None
    total = 0
    for at, letter in enumerate(text):
        worth = ROMAN[letter]
        following = ROMAN[text[at + 1]] if at + 1 < len(text) else 0
        total += -worth if worth < following else worth
    return total if total > 0 else None


def ordinal_value(word: str) -> int:
    word = DIACRITICS.sub("", word).removeprefix("ال").rstrip("ةىا")
    for index, ordinal in enumerate(ORDINAL_WORDS, start=1):
        if word == ordinal or word == ordinal.rstrip("ى"):
            return index
    return 1 if word.startswith("أول") else 0


def single(inner: str, around: str) -> Label | None:
    """One number, letter or numeral, with the brackets or stop around it as its style."""
    shape = around.replace("x", "{}")
    if re.fullmatch(DIGITS, inner):
        return Label(shape.format(inner), shape.format("1"), (number(inner),))
    if len(inner) == 1 and inner in ABJAD:
        # Arabic lists run in abjad order (أ ب ج د) or alphabetical order (أ ب ت ث).
        others: tuple[tuple[str, tuple[int, ...]], ...] = ()
        if inner in ALPHABETICAL:
            others = (("arabic-alphabetical" + around, (ALPHABETICAL.index(inner) + 1,)),)
        return Label(
            shape.format(inner), "arabic-abjad" + around, (ABJAD.index(inner) + 1,), others
        )
    case = "upper" if inner.isupper() else "lower"
    numeral = roman_value(inner)
    if len(inner) == 1 and inner.isascii():
        letter = ("letter-" + case + around, (ord(inner.lower()) - ord("a") + 1,))
        if numeral is not None:
            return Label(
                shape.format(inner), *letter, others=(("roman-" + case + around, (numeral,)),)
            )
        return Label(shape.format(inner), *letter)
    if numeral is not None and inner.isascii():
        return Label(shape.format(inner), "roman-" + case + around, (numeral,))
    return None


def read_label(text: str) -> tuple[Label, str] | None:
    """The number a paragraph starts with, and the text after it, if it starts with one."""
    text = text.lstrip(" \t ‏‎")
    if match := WORDED.match(text):
        inner = match.group("inner").strip("()")
        if inner[0].translate(ARABIC_DIGITS).isdigit():
            values = tuple(number(part) for part in inner.split("."))
        elif len(inner) == 1:
            values = (ord(inner.lower()) - ord("a") + 1,)
        else:
            values = (roman_value(inner) or 0,)
        if values[-1]:
            word = match.group("word").lower()
            written = match.group("label").rstrip(":. ")
            return Label(written, f"word-{word}", values), rest(text, match)
    if match := ARABIC_WORDED.match(text):
        inner = match.group("inner").strip("()")
        value = (
            number(inner) if inner[0].translate(ARABIC_DIGITS).isdigit() else ordinal_value(inner)
        )
        if value:
            written = match.group("label").rstrip(":.-\u2013 ")
            return Label(written, "word-" + match.group("word"), (value,)), rest(text, match)
    if match := ORDINAL.match(text):
        value = ordinal_value(match.group("inner"))
        return Label(match.group("label").rstrip(":.-\u2013 "), "ordinal", (value,)), rest(
            text, match
        )
    if match := NUMBERED.match(text):
        written = match.group("label")
        parts = tuple(number(part) for part in written.rstrip(".").split("."))
        style = "1." if len(parts) == 1 else f"dotted-{len(parts)}"
        return Label(written, style, parts), rest(text, match)
    if match := HYPHENATED.match(text):
        written = match.group("label")
        parts = tuple(number(part) for part in written.rstrip("-").split("-"))
        return Label(written, f"hyphenated-{len(parts)}", parts), rest(text, match)
    if match := BRACKETED.match(text):
        found = single(match.group("inner"), "(x)")
        if found is not None:
            return found, rest(text, match)
    if match := CLOSED.match(text):
        found = single(match.group("inner"), "x" + match.group("label")[-1])
        if found is not None:
            return found, rest(text, match)
    if match := ARABIC_LETTER.match(text):
        found = single(match.group("inner"), "x-")
        if found is not None:
            return found, rest(text, match)
    if match := BULLET.match(text):
        return Label(match.group("label"), "bullet", ()), rest(text, match)
    return None


def rest(text: str, match: re.Match[str]) -> str:
    """The text after a number, without a colon or dash set between them: "المادة (5) - نطاق"."""
    after = text[match.end() :]
    return SEPARATOR.sub("", after, count=1)


def parse_label(label: str) -> Label | None:
    """A number on its own, as Word draws one: "4.2.", "(a)", "1-1", "Section 3"."""
    found = read_label(label.strip() + " ")
    if found is None or found[1].strip():
        return None
    return found[0]


def follows(previous: Label, label: Label) -> bool:
    """Whether a number comes straight after another of the same style.

    "4.3" follows "4.2", and "5.1" follows "4.5" too: the next number at some level, with
    every level below it starting again at one.
    """
    for style, values in label.readings():
        for earlier_style, earlier in previous.readings():
            if style != earlier_style or len(values) != len(earlier) or not values:
                continue
            for at in range(len(values)):
                if (
                    values[:at] == earlier[:at]
                    and values[at] == earlier[at] + 1
                    and all(value == 1 for value in values[at + 1 :])
                ):
                    return True
    return False


def starts(label: Label) -> bool:
    """Whether a number is the first of its style: 1, a, i, or the first under its parent."""
    return any(values and values[-1] == 1 for _, values in label.readings())


def segment(label: str) -> str:
    """A number as a key segment: the document's own, without the punctuation around it.

    Digits are written in ASCII and letters keep their script, so "(أ)" is "أ", "4.2." is
    "4.2" and "Article 5" is "article-5".
    """
    text = unicodedata.normalize("NFKC", label).translate(ARABIC_DIGITS)
    text = DIACRITICS.sub("", text).lower()
    text = re.sub(r"(?<=\d)[.\-](?=\d)", lambda m: "\x00" if m.group() == "." else "\x01", text)
    text = re.sub(r"[^\w\x00\x01]+", "-", text).strip("-_")
    return text.replace("\x00", ".").replace("\x01", "-")
