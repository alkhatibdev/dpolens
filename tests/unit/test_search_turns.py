"""How the sources a search covers share its results: each law, and the organisation's own
policies, ranked by itself, then taking turns, the one whose best match is closest first.

A law's search questions score on a higher scale than any clause's words, so in one list a
source without them would sink below one with them. Ranked apart, each keeps its share.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from dpolens.engine.search import engine
from dpolens.engine.search.keyword import Candidate


def listed(*found: tuple[str, float]) -> list[Candidate]:
    return [
        Candidate(key=key, lang="en", score=score, rank=rank)
        for rank, (key, score) in enumerate(found, start=1)
    ]


EXPLAINS = {"gdpr:explains"}


def stub(
    monkeypatch: pytest.MonkeyPatch,
    meaning: dict[str | None, list[Candidate]],
    asked: dict[str, list[Candidate]] | None = None,
) -> None:
    """Each source's lists: `meaning` by law, None for the policies, and its questions."""

    def law(packs: Sequence[str]) -> str | None:
        return packs[0] if packs else None

    def clause(session: object, key: str, **_: object) -> Any:
        view = SimpleNamespace(
            key=key, archived=False, is_normative=key not in EXPLAINS, in_force_until=None
        )
        return SimpleNamespace(clause=view, breadcrumb=(), cross_references=())

    monkeypatch.setattr(engine, "keyword_search", lambda *_, **__: [])
    monkeypatch.setattr(
        engine, "vector_search", lambda *_, packs, **__: meaning.get(law(packs), [])
    )
    monkeypatch.setattr(
        engine, "nearest_questions", lambda _s, _e, _v, pack, **__: (asked or {}).get(pack, [])
    )
    monkeypatch.setattr(engine, "get_clause", clause)


def keys(
    laws: tuple[str, ...], limit: int = 10, questions: bool = False, as_of: date | None = None
) -> list[str]:
    embedder = SimpleNamespace(encode_query=lambda query: None)
    scope = SimpleNamespace(laws=laws, narrowed=True)
    found = engine.search(
        object(),  # type: ignore[arg-type]
        embedder,  # type: ignore[arg-type]
        "how long may we keep it",
        limit=limit,
        scope=scope,  # type: ignore[arg-type]
        questions=questions,
        as_of=as_of,
    )
    return [result.clause.key for result in found]


def test_the_sources_take_turns_the_closest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(
        monkeypatch,
        {
            "gdpr": listed(("gdpr:a", 0.80), ("gdpr:b", 0.79), ("gdpr:c", 0.78)),
            "uae-pdpl": listed(("uae-pdpl:a", 0.90), ("uae-pdpl:b", 0.70)),
            None: listed(("policy:a", 0.85)),
        },
    )

    assert keys(("gdpr", "uae-pdpl")) == [
        "uae-pdpl:a",
        "policy:a",
        "gdpr:a",
        "uae-pdpl:b",
        "gdpr:b",
        "gdpr:c",
    ]


def test_a_law_s_questions_count_towards_how_close_its_best_match_came(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub(
        monkeypatch,
        {"gdpr": listed(("gdpr:a", 0.80)), "uae-pdpl": listed(("uae-pdpl:a", 0.85))},
        asked={"gdpr": listed(("gdpr:q", 0.95))},
    )

    assert keys(("gdpr", "uae-pdpl"), questions=True)[0].startswith("gdpr:")
    # On another day the questions are not used, and the law's own words decide.
    assert keys(("gdpr", "uae-pdpl"), questions=True, as_of=date(2025, 1, 1))[0] == "uae-pdpl:a"


def test_a_question_brings_its_clause_into_its_law_s_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub(
        monkeypatch,
        {"gdpr": listed(("gdpr:a", 0.80), ("gdpr:b", 0.70))},
        asked={"gdpr": listed(("gdpr:found-by-a-question", 0.95), ("gdpr:b", 0.60))},
    )

    assert "gdpr:found-by-a-question" in keys(("gdpr",), questions=True)
    assert "gdpr:found-by-a-question" not in keys(("gdpr",), questions=False)


def test_a_source_that_runs_out_leaves_its_turns_to_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub(
        monkeypatch,
        {
            "gdpr": listed(*((f"gdpr:{n}", 0.9 - n / 100) for n in range(8))),
            None: listed(("policy:a", 0.95)),
        },
    )

    found = keys(("gdpr",), limit=5)

    assert found[0] == "policy:a"
    assert found[1:] == ["gdpr:0", "gdpr:1", "gdpr:2", "gdpr:3"]


def test_where_scores_cannot_separate_them_the_clause_that_obliges_comes_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tied, the clause that explains would come first by its key alone.
    stub(monkeypatch, {"gdpr": listed(("gdpr:explains", 0.8), ("gdpr:obliges", 0.8))})

    assert keys(("gdpr",)) == ["gdpr:obliges", "gdpr:explains"]
