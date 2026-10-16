"""What changed between versions of a policy, and which clause each one continues.

Keys follow the printed numbers in each version, so a key alone cannot say which earlier clause
a new one continues: text does. Each clause of a new version is matched to the previous
version's by key and by text, and marked unchanged, modified, moved or added; an earlier clause
nothing continues was removed. A move, a number that now names a different rule, and new words
too far from the old to be sure of, are flags the reviewer confirms, because matching by text
can be wrong: two rows of a retention schedule share most of their words.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

Change = Literal["added", "modified", "moved", "unchanged"]

SAME_KEY_SIMILARITY = 0.5
"""Under the same key, text this alike is the same rule, reworded."""

MOVED_SIMILARITY = 0.8
"""Under a different key, text must be this alike to be the same rule, renumbered."""


@dataclass(frozen=True)
class Earlier:
    """A clause of the previous version."""

    id: uuid.UUID
    key: str
    label: str | None
    heading: str | None
    text: str


@dataclass(frozen=True)
class Later:
    """A clause of the new version."""

    key: str
    label: str | None
    heading: str | None
    text: str


@dataclass(frozen=True)
class Match:
    change: Change
    earlier: Earlier | None
    score: float = 1.0
    """How alike the two clauses' words are, from 0 to 1."""


@dataclass
class Matching:
    matches: dict[str, Match] = field(default_factory=dict)
    """For each new key, what it continues."""

    removed: list[Earlier] = field(default_factory=list)
    """Earlier clauses nothing in the new version continues."""

    reused: dict[str, tuple[Earlier, str | None]] = field(default_factory=dict)
    """A new key that named a different rule before: that rule, and its new key if any."""


def words(clause: Earlier | Later) -> list[str]:
    """A clause's heading and text as words, for comparing one version's with another's."""
    return re.findall(r"\w+", f"{clause.heading or ''} {clause.text}".lower())


def similarity(left: list[str], right: list[str]) -> float:
    if not left and not right:
        return 1.0
    shared = set(left) & set(right)
    if not shared or len(shared) * 2 < 0.4 * (len(set(left)) + len(set(right))):
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def match(earlier: Sequence[Earlier], later: Sequence[Later]) -> Matching:
    """Pair each new clause with the earlier clause it continues, best evidence first."""
    result = Matching()
    before = {clause.key: clause for clause in earlier}
    texts = {clause.id: words(clause) for clause in earlier}
    open_earlier = {clause.id: clause for clause in earlier}
    open_later = {clause.key: clause for clause in later}

    def pair(new: Later, old: Earlier, change: Change, score: float = 1.0) -> None:
        result.matches[new.key] = Match(change=change, earlier=old, score=score)
        open_later.pop(new.key)
        open_earlier.pop(old.id)

    # The same words anywhere, preferring the same key, then the same key with words changed.
    by_text: dict[tuple[str, ...], list[Earlier]] = {}
    for clause in earlier:
        by_text.setdefault(tuple(texts[clause.id]), []).append(clause)
    for new in list(later):
        candidates = [c for c in by_text.get(tuple(words(new)), []) if c.id in open_earlier]
        if not candidates or not words(new):
            continue
        same = next((c for c in candidates if c.key == new.key), None)
        old = same or candidates[0]
        pair(new, old, "unchanged" if old.key == new.key else "moved")
    for key, new in list(open_later.items()):
        same_key = before.get(key)
        if same_key is None or same_key.id not in open_earlier:
            continue
        score = similarity(words(new), texts[same_key.id])
        if score >= SAME_KEY_SIMILARITY:
            pair(new, same_key, "modified", score)

    # Renumbered and reworded: the closest earlier clause, if it is close enough.
    scored = sorted(
        (
            (similarity(words(new), texts[old.id]), new.key, old.id)
            for new in open_later.values()
            for old in open_earlier.values()
        ),
        reverse=True,
    )
    for score, key, old_id in scored:
        if score < MOVED_SIMILARITY:
            break
        if key in open_later and old_id in open_earlier:
            pair(open_later[key], open_earlier[old_id], "moved", score)

    for key in open_later:
        result.matches[key] = Match(change="added", earlier=None)
    result.removed = sorted(open_earlier.values(), key=lambda clause: clause.key)

    # A number that named one rule and now names another, which a citation without its
    # version would quietly follow.
    went: dict[uuid.UUID, str] = {
        found.earlier.id: key for key, found in result.matches.items() if found.earlier
    }
    for key, found in result.matches.items():
        named = before.get(key)
        if named is not None and (found.earlier is None or found.earlier.id != named.id):
            result.reused[key] = (named, went.get(named.id))
    return result
