"""Taking the personal data out of a question before it is stored.

The query log's promise to a developer is that what they typed is kept redacted
and expires. Redaction is pattern matching, so it misses things, which is why the
retention exists as well: one bounds what survives, the other bounds how long.

An operator may add a pattern and can never remove one. A Gulf instance will want
an identifier format the built-ins miss, and no instance should be able to turn
redaction off. Added patterns are capped in length, rejected if they match
nothing, and run with a timeout, because a regular expression from outside this
repository sits on the path of every search and catastrophic backtracking is the
easiest denial of service there is.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import regex

type Finder = Callable[[str], list[tuple[int, int]]]

PLACEHOLDER = "[redacted:{name}]"
PATTERN_TIMEOUT = 0.1
"""Seconds an added pattern may spend on one query before it is abandoned."""

MAX_PATTERN = 200
"""Characters. A pattern longer than this is a program, not a pattern."""

EMAIL = regex.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", regex.UNICODE)
DIGIT_RUN = regex.compile(r"\d[\d\s.-]{11,21}\d")
"""Card-length runs of digits, which are checked with Luhn before being hidden."""

IBAN = regex.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
EMIRATES_ID = regex.compile(r"\b784[-\s]?\d{4}[-\s]?\d{7}[-\s]?\d\b")
PHONE = regex.compile(r"(?<![\w.])\+?\d[\d\s().-]{5,20}\d(?![\w.])")
PHONE_DIGITS = (7, 15)
"""A phone number holds seven to fifteen digits: E.164 allows no more.

The cap is what keeps a sixteen digit reference number from being called a phone
number, and the floor keeps a version like 5.2.1 and a year like 2018 out of it.
"""


@dataclass(frozen=True)
class Redacted:
    """What is safe to store, and what was taken out of it."""

    text: str
    count: int
    types: tuple[str, ...]


def luhn(digits: str) -> bool:
    """Whether a run of digits is a plausible card number.

    Without this, any long number is treated as a card, which teaches everybody
    that redaction is noise.
    """
    total = 0
    for position, character in enumerate(reversed(digits)):
        value = int(character)
        if position % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _hide(text: str, name: str, matches: list[tuple[int, int]]) -> tuple[str, int]:
    """Replace spans back to front, so earlier offsets stay valid."""
    for start, end in reversed(matches):
        text = text[:start] + PLACEHOLDER.format(name=name) + text[end:]
    return text, len(matches)


def _card_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for found in DIGIT_RUN.finditer(text):
        digits = regex.sub(r"\D", "", found.group())
        if 13 <= len(digits) <= 19 and luhn(digits):
            spans.append(found.span())
    return spans


def _phone_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for found in PHONE.finditer(text):
        digits = sum(character.isdigit() for character in found.group())
        if PHONE_DIGITS[0] <= digits <= PHONE_DIGITS[1]:
            spans.append(found.span())
    return spans


def _spans_of(pattern: regex.Pattern[str]) -> Finder:
    def find(text: str) -> list[tuple[int, int]]:
        return [match.span() for match in pattern.finditer(text)]

    return find


def _iban_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for found in IBAN.finditer(text):
        candidate = found.group()
        rearranged = candidate[4:] + candidate[:4]
        numeric = "".join(
            str(int(character, 36)) if character.isalpha() else character
            for character in rearranged
        )
        if numeric.isdigit() and int(numeric) % 97 == 1:
            spans.append(found.span())
    return spans


def redact(text: str, extra: Mapping[str, str] | None = None) -> Redacted:
    """Hide what looks like somebody's personal data, and say what was hidden.

    Two things about the order. Each pattern runs against what the previous ones
    left, because replacing a span invalidates every offset after it. And an
    operator's own patterns run first: a local identifier format is more specific
    than the general shapes here, so the instance that added it should see it
    named on the row rather than called a phone number.
    """
    found: list[str] = []
    total = 0

    finders: list[tuple[str, Finder]] = [
        (name, _added_finder(pattern)) for name, pattern in (extra or {}).items()
    ]
    finders += [
        ("card", _card_spans),
        ("iban", _iban_spans),
        ("emirates_id", _spans_of(EMIRATES_ID)),
        ("email", _spans_of(EMAIL)),
        ("phone", _phone_spans),
    ]

    for name, find in finders:
        spans = find(text)
        if not spans:
            continue
        text, hidden = _hide(text, name, spans)
        total += hidden
        found.append(name)

    return Redacted(text=text, count=total, types=tuple(found))


def _added_finder(pattern: str) -> Finder:
    """Run an operator's pattern under a timeout, and give up rather than hang.

    A pattern that times out or fails to compile leaves the text as it was, and
    the row is still written with whatever the other patterns did hide. Storing
    the question unredacted would be the worse failure, and the types on the row
    say which patterns actually ran.
    """

    def find(text: str) -> list[tuple[int, int]]:
        try:
            compiled = regex.compile(pattern)
            return [match.span() for match in compiled.finditer(text, timeout=PATTERN_TIMEOUT)]
        except regex.error, TimeoutError:
            return []

    return find


def check_pattern(name: str, pattern: str) -> None:
    """Refuse a pattern at startup rather than on the first question.

    A pattern that matches the empty string would replace every position in the
    text, which is not redaction but destruction.
    """
    if not name.isidentifier():
        raise ValueError(f"redaction pattern names are identifiers, and {name!r} is not")
    if len(pattern) > MAX_PATTERN:
        raise ValueError(f"the {name} pattern is longer than {MAX_PATTERN} characters")
    try:
        compiled = regex.compile(pattern)
    except regex.error as broken:
        raise ValueError(f"the {name} pattern does not compile: {broken}") from broken
    if compiled.search(""):
        raise ValueError(
            f"the {name} pattern matches the empty string, which would hide everything"
        )
