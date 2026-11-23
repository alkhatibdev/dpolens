"""A candidate that cannot be an answer gives its place to the next one.

The retrievers rank clauses without knowing whether a clause's policy is archived, whether
it is in force on the date asked about, or whether a law has ended its words. Those are
passed over after fusion, and the next candidates take their places, so a search still
returns as many results as were asked for.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from dpolens.engine.search import engine
from dpolens.engine.search.fuse import Fused

ARCHIVED = [f"old-policy:p{number}" for number in range(1, 8)]
NOT_IN_FORCE = "later-policy:p1"
ENDED = "testlaw:art-6"
ANSWER = "policy:4.2"


def detail(key: str, archived: bool) -> Any:
    clause = SimpleNamespace(
        key=key,
        archived=archived,
        is_normative=True,
        pack_slug=None,
        in_force_until=date(2020, 1, 1) if key == ENDED else None,
    )
    return SimpleNamespace(clause=clause, breadcrumb=(), cross_references=())


@pytest.fixture
def ranked(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [*ARCHIVED, NOT_IN_FORCE, ENDED, ANSWER]
    fused = [
        Fused(key=key, lang="en", score=1.0 - index / 100, ranks={"keyword": index + 1})
        for index, key in enumerate(keys)
    ]

    def get_clauses(session: object, wanted: list[str], **_: object) -> dict[str, Any]:
        """A key not in force on the day asked about is left out, as the reader leaves it."""
        return {key: detail(key, archived=key in ARCHIVED) for key in wanted if key != NOT_IN_FORCE}

    monkeypatch.setattr(engine, "keyword_search", lambda *_, **__: [])
    monkeypatch.setattr(engine, "vector_search", lambda *_, **__: [])
    monkeypatch.setattr(engine, "fuse", lambda *_, **__: fused)
    monkeypatch.setattr(engine, "get_clauses", get_clauses)
    monkeypatch.setattr(engine, "questions_on", lambda session: False)


def test_archived_ended_and_not_yet_in_force_clauses_leave_no_slot_empty(ranked: None) -> None:
    # No law loaded: the organisation's policies are the one source searched.
    scope = SimpleNamespace(laws=(), narrowed=False)

    # The query is encoded once, for meaning search and the search questions alike.
    embedder = SimpleNamespace(encode_query=lambda query: None)

    found = engine.search(object(), embedder, "staff records", limit=1, scope=scope)  # type: ignore[arg-type]

    assert [result.clause.key for result in found] == [ANSWER]
