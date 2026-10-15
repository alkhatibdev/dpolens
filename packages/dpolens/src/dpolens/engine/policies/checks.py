"""The checks every parse runs before a person looks at it.

Coverage: every paragraph of the file is in exactly one clause or one set-aside block, and
every character the reader found is in one of them. Numbering: siblings numbered in the same
style follow one another, with no gap, repeat or step back. A check is what the parser runs;
what it finds is a flag, which the reviewer resolves or accepts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from dpolens.engine.policies.blocks import ReadFile
from dpolens.engine.policies.patterns import Label, follows, parse_label, starts
from dpolens.engine.policies.structure import Built, Node
from dpolens.engine.policies.tree import Clause, Coverage, Flag


def printed(text: str) -> int:
    """The characters a reader sees: spacing is layout, not text."""
    return sum(1 for character in text if not character.isspace())


def nodes(roots: Sequence[Node]) -> list[Node]:
    found: list[Node] = []
    for node in roots:
        found.append(node)
        found.extend(nodes(node.children))
    return found


def check_coverage(read: ReadFile, built: Built) -> tuple[Coverage, list[Flag]]:
    paragraphs = {paragraph.position: paragraph for paragraph in read.paragraphs()}
    in_clauses: Counter[int] = Counter()
    for node in nodes(built.roots):
        in_clauses.update(node.positions)
    set_aside: Counter[int] = Counter()
    for block in built.set_aside:
        set_aside.update(block.positions)
    flags: list[Flag] = []
    for position, paragraph in paragraphs.items():
        times = in_clauses[position] + set_aside[position] + built.spacing.count(position)
        if times == 1:
            continue
        where = "in no clause" if times == 0 else f"in {times} places"
        flags.append(
            Flag(
                kind="coverage_gap",
                detail=f"This text is {where}: {paragraph.text.strip()[:80]!r}.",
                position=position,
            )
        )
    if read.missed:
        kinds = ", ".join(read.unread) or "parts this reader does not know"
        flags.append(
            Flag(
                kind="coverage_gap",
                detail=f"{read.missed} characters of text inside {kinds} were not read.",
            )
        )
    coverage = Coverage(
        characters=sum(printed(p.text) for p in paragraphs.values()) + read.missed,
        in_clauses=sum(printed(paragraphs[at].text) for at in in_clauses if at in paragraphs),
        set_aside=sum(printed(paragraphs[at].text) for at in set_aside if at in paragraphs),
        missed=read.missed,
    )
    return coverage, flags


def check_numbering(clauses: Sequence[Clause]) -> list[Flag]:
    """Siblings numbered in one style follow each other: 1, 2, 3, never 1, 3 or 2, 2."""
    flags: list[Flag] = []
    previous: dict[str, tuple[Label, Clause]] = {}
    interrupted = False
    for clause in clauses:
        label = parse_label(clause.label) if clause.label else None
        if label is None or label.bullet:
            interrupted = True
        else:
            earlier = previous.get(label.style)
            # A list that starts again at one after other text is a new list, not a slip.
            restarted = interrupted and starts(label)
            if earlier is not None and not follows(earlier[0], label) and not restarted:
                what = "repeats" if earlier[0].values == label.values else "follows"
                flags.append(
                    Flag(
                        kind="numbering_gap",
                        detail=f"{label.text} {what} {earlier[0].text}.",
                        key=clause.key,
                    )
                )
            for style, _ in label.readings():
                previous[style] = (label, clause)
            interrupted = False
        flags.extend(check_numbering(clause.children))
    return flags


def check_keys(clauses: Sequence[Clause]) -> list[Flag]:
    """Every key names one clause. Two that collide are the parser's to own up to."""
    counted = Counter(clause.key for root in clauses for clause in root.walk())
    return [
        Flag(kind="numbering_gap", detail=f"{key} names {times} clauses.", key=key)
        for key, times in counted.items()
        if times > 1
    ]
