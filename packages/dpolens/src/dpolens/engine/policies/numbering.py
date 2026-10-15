"""Word's automatic numbers, drawn the way Word draws them.

An automatic number is not text in the file. Word draws it from a list definition, a counter
for each of its levels and the level's pattern, such as "%1.%2". A policy's clause keys come
from these numbers, so they are rendered here exactly: a definition's counters are shared by
every list that uses it, a list that asks to start again does so where it first appears, and a
level restarts when a level above it is used, unless the definition says otherwise.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from dpolens.engine.policies.blocks import Number

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PLACEHOLDER = re.compile(r"%([1-9])")


def words(text: str) -> tuple[str, ...]:
    return tuple(text.split())


ARABIC_ALPHA = words("أ ب ت ث ج ح خ د ذ ر ز س ش ص ض ط ظ ع غ ف ق ك ل م ن هـ و ي")
ARABIC_ABJAD = words("أ ب ج د هـ و ز ح ط ي ك ل م ن س ع ف ص ق ر ش ت ث خ ذ ض ظ غ")
ROMAN_VALUES = (1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1)
ROMAN_LETTERS = words("m cm d cd c xc l xl x ix v iv i")
CARDINALS = words(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty"
)
ORDINALS = words(
    "zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth"
)


def attribute(element: Element | None, name: str = "val") -> str | None:
    return None if element is None else element.get(W + name)


def roman(value: int) -> str:
    out = ""
    for amount, letters in zip(ROMAN_VALUES, ROMAN_LETTERS, strict=True):
        while value >= amount:
            out, value = out + letters, value - amount
    return out


def repeated(value: int, alphabet: tuple[str, ...]) -> str:
    """Word's way past the alphabet's end: a, b ... z, then aa, bb."""
    return alphabet[(value - 1) % len(alphabet)] * ((value - 1) // len(alphabet) + 1)


def drawn(value: int, form: str) -> str | None:
    """A counter in one of Word's formats, or None for a format this does not draw."""
    latin = tuple(chr(code) for code in range(ord("a"), ord("z") + 1))
    match form:
        case "decimal" | "decimalEnclosedFullstop":
            return str(value)
        case "decimalZero":
            return f"{value:02d}"
        case "decimalEnclosedParen":
            return f"({value})"
        case "decimalEnclosedCircle" if 1 <= value <= 20:
            return chr(0x2460 + value - 1)
        case "lowerLetter":
            return repeated(value, latin)
        case "upperLetter":
            return repeated(value, latin).upper()
        case "lowerRoman":
            return roman(value)
        case "upperRoman":
            return roman(value).upper()
        case "ordinal":
            teens = 10 <= value % 100 <= 20
            suffix = "th" if teens else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
            return f"{value}{suffix}"
        case "cardinalText" if value < len(CARDINALS):
            return CARDINALS[value].capitalize()
        case "ordinalText" if value < len(ORDINALS):
            return ORDINALS[value].capitalize()
        case "arabicAlpha":
            return repeated(value, ARABIC_ALPHA)
        case "arabicAbjad":
            return repeated(value, ARABIC_ABJAD)
        case "hindiNumbers":
            return str(value).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
        case "decimalFullWidth" | "decimalFullWidth2":
            return str(value).translate(str.maketrans("0123456789", "０１２３４５６７８９"))
        case "none" | "bullet":
            return ""
        case _:
            return None


@dataclass(frozen=True)
class Level:
    start: int = 1
    form: str = "decimal"
    pattern: str = ""
    legal: bool = False
    """Word's legal numbering: every level in the number is shown as a decimal."""

    restart: int | None = None
    """Restart after this level (from 1) is used; None after any higher level, 0 never."""

    style: str | None = None
    """The paragraph style tied to this level, which numbers a paragraph by itself."""


def read_level(element: Element) -> Level:
    def number(tag: str) -> int | None:
        value = attribute(element.find(W + tag))
        return int(value) if value is not None and value.lstrip("-").isdigit() else None

    legal = element.find(W + "isLgl")
    start = number("start")
    return Level(
        start=1 if start is None else start,
        form=attribute(element.find(W + "numFmt")) or "decimal",
        pattern=attribute(element.find(W + "lvlText")) or "",
        legal=legal is not None and attribute(legal) not in ("0", "false", "off"),
        restart=number("lvlRestart"),
        style=attribute(element.find(W + "pStyle")),
    )


@dataclass
class Definition:
    levels: dict[int, Level]
    link: str | None = None
    """A numbering style this definition stands for, whose own definition is the real one."""


@dataclass
class Instance:
    definition: str
    starts: dict[int, int]
    levels: dict[int, Level]
    """Levels this list replaces for itself alone."""


class Numbering:
    """A file's list definitions, and the counters Word keeps while it draws them."""

    def __init__(self, root: Element | None, numbering_style: Callable[[str], str | None]) -> None:
        self.definitions: dict[str, Definition] = {}
        self.instances: dict[str, Instance] = {}
        self.counters: dict[str, dict[int, int]] = {}
        self.begun: set[str] = set()
        self.undrawn: set[str] = set()
        """Formats this did not draw, shown as decimals, for a notice to the reviewer."""

        self.numbering_style = numbering_style
        if root is None:
            return
        for element in root.findall(W + "abstractNum"):
            levels = {
                int(attribute(lvl, "ilvl") or 0): read_level(lvl)
                for lvl in element.findall(W + "lvl")
            }
            link = attribute(element.find(W + "numStyleLink"))
            self.definitions[attribute(element, "abstractNumId") or ""] = Definition(levels, link)
        for element in root.findall(W + "num"):
            definition = attribute(element.find(W + "abstractNumId"))
            if definition is None:
                continue
            starts: dict[int, int] = {}
            own: dict[int, Level] = {}
            for override in element.findall(W + "lvlOverride"):
                level = int(attribute(override, "ilvl") or 0)
                start = attribute(override.find(W + "startOverride"))
                if start is not None and start.isdigit():
                    starts[level] = int(start)
                replaced = override.find(W + "lvl")
                if replaced is not None:
                    own[level] = read_level(replaced)
            self.instances[attribute(element, "numId") or ""] = Instance(definition, starts, own)

    def resolve(self, definition: str, seen: frozenset[str] = frozenset()) -> str:
        """Follow a definition that stands for a numbering style to the one that is used."""
        found = self.definitions.get(definition)
        if found is None or found.link is None or definition in seen:
            return definition
        instance = self.numbering_style(found.link)
        if instance is None or instance not in self.instances:
            return definition
        return self.resolve(self.instances[instance].definition, seen | {definition})

    def levels_of(self, num_id: str) -> tuple[str, dict[int, Level]] | None:
        instance = self.instances.get(num_id)
        if instance is None:
            return None
        definition = self.resolve(instance.definition)
        levels = dict(self.definitions.get(definition, Definition({})).levels)
        levels.update(instance.levels)
        return definition, levels

    def level_for_style(self, num_id: str, style: str | None) -> int:
        """The level a paragraph takes from its style, when the style numbers it."""
        found = self.levels_of(num_id)
        if found is not None and style is not None:
            for index, level in found[1].items():
                if level.style == style:
                    return index
        return 0

    def number(self, num_id: str, level: int) -> Number | None:
        """The next number in this list at this level, advancing Word's counters."""
        found = self.levels_of(num_id)
        if found is None or level not in found[1]:
            return None
        definition, levels = found
        counters = self.counters.setdefault(definition, {})
        instance = self.instances[num_id]
        if num_id not in self.begun:
            # A list that starts again does so where it first appears, and only there.
            self.begun.add(num_id)
            for restarted, start in instance.starts.items():
                counters[restarted] = start - 1
                for deeper in [at for at in counters if at > restarted]:
                    del counters[deeper]
        current = levels[level]
        counters[level] = counters.get(level, current.start - 1) + 1
        for deeper in [at for at in counters if at > level]:
            rule = levels.get(deeper, Level()).restart
            if rule is None or (rule != 0 and rule - 1 <= level):
                del counters[deeper]
        if current.form == "bullet":
            return Number(label="•", list_id=definition, level=level, bullet=True)

        def placeholder(match: re.Match[str]) -> str:
            at = int(match.group(1)) - 1
            shown = levels.get(at, Level())
            value = counters.get(at, shown.start)
            legal = current.legal and shown.form not in ("none", "bullet")
            form = "decimal" if legal else shown.form
            text = drawn(value, form)
            if text is None:
                self.undrawn.add(form)
                text = str(value)
            return text

        label = PLACEHOLDER.sub(placeholder, current.pattern).strip()
        if not label:
            return None
        return Number(label=label, list_id=definition, level=level, bullet=False)
