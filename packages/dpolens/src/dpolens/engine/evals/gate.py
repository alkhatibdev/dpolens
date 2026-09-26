"""Deciding whether retrieval got worse.

The pack, the questions and the model are fixed, so a drop in recall has one
possible cause: a change to retrieval. The comparison is against the published
interval rather than the published number, because a fifty-question set moves
by a few points on its own and a gate that fires on noise gets switched off.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Verdict:
    pack: str
    measured: float
    published: float
    floor: float

    @property
    def is_regression(self) -> bool:
        return self.measured < self.floor

    def __str__(self) -> str:
        state = "REGRESSION" if self.is_regression else "ok"
        return (
            f"{self.pack}: recall@5 {self.measured:.2f} against a published "
            f"{self.published:.2f} (interval floor {self.floor:.2f})  {state}"
        )


def compare(pack: str, measured: float, published_run: dict[str, Any]) -> Verdict:
    """Measure today's score against what was published."""
    interval = published_run.get("interval") or [0.0, 1.0]
    return Verdict(
        pack=pack,
        measured=measured,
        published=float(published_run.get("recall_at_5", 0.0)),
        floor=float(interval[0]),
    )
