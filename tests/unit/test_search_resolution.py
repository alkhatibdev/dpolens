"""A candidate that cannot be an answer gives its place to the next one.

The retrievers rank clauses without knowing whether a clause's policy is archived or whether
it is in force on the date asked about. Those are passed over after fusion, and the next
candidates take their places, so a search still returns as many results as were asked for.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dpolens.engine.documents.read import ClauseNotFound
from dpolens.engine.search import engine
from dpolens.engine.search.fuse import Fused

ARCHIVED = [f"old-policy:p{number}" for number in range(1, 8)]
NOT_IN_FORCE = "later-policy:p1"
ANSWER = "policy:4.2"


def detail(key: str, archived: bool) -> Any:
    clause = SimpleNamespace(key=key, archived=archived, is_normative=True, pack_slug=None)
    return SimpleNamespace(clause=clause, breadcrumb=(), cross_references=())


@pytest.fixture
def ranked(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [*ARCHIVED, NOT_IN_FORCE, ANSWER]
    fused = [
        Fused(key=key, lang="en", score=1.0 - index / 100, ranks={"keyword": index + 1})
        for index, key in enumerate(keys)
    ]

    def get_clause(session: object, key: str, **_: object) -> Any:
        if key == NOT_IN_FORCE:
            raise ClauseNotFound(key)
        return detail(key, archived=key in ARCHIVED)

    monkeypatch.setattr(engine, "keyword_search", lambda *_, **__: [])
    monkeypatch.setattr(engine, "vector_search", lambda *_, **__: [])
    monkeypatch.setattr(engine, "fuse", lambda *_, **__: fused)
    monkeypatch.setattr(engine, "get_clause", get_clause)
    monkeypatch.setattr(engine, "scope_for", lambda session: SimpleNamespace(narrowed=False))


def test_archived_and_not_yet_in_force_clauses_leave_no_slot_empty(ranked: None) -> None:
    scope = SimpleNamespace(narrowed=False, is_selected=lambda pack: True)

    found = engine.search(object(), object(), "staff records", limit=1, scope=scope)  # type: ignore[arg-type]

    assert [result.clause.key for result in found] == [ANSWER]
