"""A result as a whole rule: the words a matched clause belongs to, with what sits beneath.

A point such as Article 17(1)(b) says nothing by itself: the rule is "the data subject shall
have the right to obtain ... erasure ... where one of the following grounds applies", and (b) is
one of the grounds. So search can return the rule a match belongs to rather than the match
alone. Which clause that is follows from the text's own structure, the same for every law: go
up from the match while the clause above has words of its own, since words above a clause are
what introduce it. A heading is not words of its own, so the walk stops below an article that
is only a title, and it reaches an article that opens with "The following cases shall be
excluded from such prohibition:".

A rule comes back whole when it is short enough to read as one. A longer one, such as a law's
list of definitions under "For the purposes of this Regulation:", comes back as its own words
and the clauses the search reached, each with everything beneath it.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date

from dpolens.engine.documents.read import ClauseView

WHOLE = 2500
"""The most characters a rule has and still comes back whole. Chosen on the practice sets: a
lower limit cut answers out of the rules it shortened, and a higher one added text and no
answers."""


def rule_of(clause: ClauseView, breadcrumb: Sequence[ClauseView]) -> ClauseView:
    """The clause whose words `clause` belongs to: itself, or the highest clause above it that
    is reached through clauses with words of their own."""
    chain = [*breadcrumb, clause]
    at = len(chain) - 1
    while at > 0 and chain[at - 1].text.strip():
        at -= 1
    return chain[at]


def shown(
    rule: ClauseView,
    beneath: Sequence[ClauseView],
    reached: Collection[str],
    as_of: date,
) -> tuple[tuple[ClauseView, ...], bool]:
    """What comes back beneath a rule's own words, and whether that is all of it.

    `beneath` is everything under the rule in reading order, and `reached` the keys of its
    clauses the search came to. Words a law has ended are left out either way.
    """
    current = [clause for clause in beneath if not ended(clause, as_of)]
    if len(rule.text) + sum(len(clause.text) for clause in current) <= WHOLE:
        return tuple(current), True

    kept: list[ClauseView] = []
    under: int | None = None
    for clause in current:
        if under is not None and clause.depth > under:
            kept.append(clause)
            continue
        under = None
        if clause.key in reached:
            kept.append(clause)
            under = clause.depth
    return tuple(kept), len(kept) == len(current)


def ended(clause: ClauseView, as_of: date) -> bool:
    """Whether a law ended these words on or before `as_of`."""
    return clause.in_force_until is not None and clause.in_force_until <= as_of
