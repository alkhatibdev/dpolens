"""A result as a whole rule, on clauses built by hand: which clause a match belongs to, and what
comes back beneath it."""

from __future__ import annotations

from datetime import date

import pytest

from dpolens.engine.documents.read import ClauseView
from dpolens.engine.search.rules import REACHED, WHOLE, rule_of, shown

TODAY = date(2026, 11, 23)


def clause(key: str, text: str = "", depth: int = 0, until: date | None = None) -> ClauseView:
    return ClauseView(
        key=key,
        clause_type="paragraph",
        label=None,
        heading=None,
        text=text,
        lang="en",
        is_authoritative=True,
        is_normative=True,
        depth=depth,
        document_title="A law",
        document_slug="law",
        version_label="1",
        effective_date=date(2020, 1, 1),
        in_force_until=until,
    )


TITLE = clause("law:art-17", "", 0)
OPENING = clause("law:art-17:para-1", "The data subject shall have the right to erasure where:", 1)
GROUND = clause("law:art-17:para-1:pt-b", "the data subject withdraws consent;", 2)


def test_a_point_belongs_to_the_paragraph_whose_words_introduce_it() -> None:
    assert rule_of(GROUND, [TITLE, OPENING]).key == "law:art-17:para-1"


def test_an_article_that_is_only_a_title_does_not_take_its_paragraphs() -> None:
    assert rule_of(OPENING, [TITLE]).key == "law:art-17:para-1"


def test_an_article_whose_own_words_introduce_its_cases_takes_them() -> None:
    """As the UAE law's Article 4 does: "The following cases shall be excluded from such
    prohibition:", with each case a numbered paragraph."""
    article = clause("law:art-4", "Processing without consent is prohibited, except:", 0)
    case = clause("law:art-4:para-1", "If the processing protects the public interest.", 1)

    assert rule_of(case, [article]).key == "law:art-4"


def test_the_walk_goes_as_high_as_words_reach() -> None:
    article = clause("law:art-9", "The following applies:", 0)
    point = clause("law:art-9:para-2:pt-a", "explicit consent;", 2)
    between = clause("law:art-9:para-2", "Paragraph 1 shall not apply where:", 1)

    assert rule_of(point, [article, between]).key == "law:art-9"


def test_a_clause_with_nothing_above_it_is_its_own_rule() -> None:
    alone = clause("law:art-6:para-4", "Where processing is for another purpose ...", 1)

    assert rule_of(alone, []).key == "law:art-6:para-4"


def test_a_short_rule_comes_back_whole() -> None:
    beneath = [GROUND, clause("law:art-17:para-1:pt-c", "the data subject objects;", 2)]

    kept, whole = shown(OPENING, beneath, reached=[GROUND.key], as_of=TODAY)

    assert [each.key for each in kept] == [each.key for each in beneath]
    assert whole


def test_a_long_rule_comes_back_as_its_words_and_what_the_search_reached() -> None:
    """A list of definitions under "For the purposes of this Regulation:" is the long case."""
    opening = clause("law:art-4", "For the purposes of this Regulation:", 0)
    definitions = [
        clause(f"law:art-4:pt-{number}", "x" * 200, 1) for number in range(1, WHOLE // 200 + 2)
    ]

    kept, whole = shown(
        opening, definitions, reached=["law:art-4:pt-5", "law:art-4:pt-2"], as_of=TODAY
    )

    assert [each.key for each in kept] == ["law:art-4:pt-2", "law:art-4:pt-5"]
    assert not whole


def test_a_long_rule_comes_with_only_the_clauses_the_search_ranked_highest() -> None:
    """A question about one definition is not answered with most of the list."""
    opening = clause("law:art-4", "For the purposes of this Regulation:", 0)
    definitions = [
        clause(f"law:art-4:pt-{number}", "t" * 200, 1) for number in range(1, WHOLE // 200 + 2)
    ]
    ranked = ["law:art-4:pt-9", "law:art-4:pt-3", "law:art-4:pt-5", "law:art-4:pt-1"]

    kept, _ = shown(opening, definitions, reached=ranked, as_of=TODAY)

    assert REACHED == 2
    assert [each.key for each in kept] == ["law:art-4:pt-3", "law:art-4:pt-9"]


def test_the_rule_s_own_words_take_no_place_among_the_clauses_shown() -> None:
    opening = clause("law:art-4", "For the purposes of this Regulation:", 0)
    definitions = [
        clause(f"law:art-4:pt-{number}", "t" * 200, 1) for number in range(1, WHOLE // 200 + 2)
    ]

    kept, _ = shown(
        opening,
        definitions,
        reached=["law:art-4", "law:art-4:pt-7", "law:art-4:pt-2"],
        as_of=TODAY,
    )

    assert [each.key for each in kept] == ["law:art-4:pt-2", "law:art-4:pt-7"]


def test_a_reached_clause_comes_with_everything_beneath_it() -> None:
    opening = clause("law:art-9:para-2", "y" * WHOLE, 0)
    point = clause("law:art-9:para-2:pt-g", "substantial public interest, on the basis of:", 1)
    beneath = [
        clause("law:art-9:para-2:pt-a", "explicit consent;", 1),
        point,
        clause("law:art-9:para-2:pt-g:i", "Union law;", 2),
        clause("law:art-9:para-2:pt-g:ii", "Member State law;", 2),
        clause("law:art-9:para-2:pt-h", "preventive medicine;", 1),
    ]

    kept, whole = shown(opening, beneath, reached=[point.key], as_of=TODAY)

    assert [each.key for each in kept] == [
        "law:art-9:para-2:pt-g",
        "law:art-9:para-2:pt-g:i",
        "law:art-9:para-2:pt-g:ii",
    ]
    assert not whole


def test_a_rule_whose_every_clause_was_reached_is_whole_however_long() -> None:
    opening = clause("law:art-4", "z" * WHOLE, 0)
    beneath = [clause("law:art-4:pt-1", "a term;", 1)]

    kept, whole = shown(opening, beneath, reached=["law:art-4:pt-1"], as_of=TODAY)

    assert [each.key for each in kept] == ["law:art-4:pt-1"]
    assert whole


def test_words_a_law_has_ended_are_left_out() -> None:
    ended = clause("law:art-17:para-1:pt-f", "a ground repealed last year;", 2, TODAY)

    kept, whole = shown(OPENING, [GROUND, ended], reached=[GROUND.key, ended.key], as_of=TODAY)

    assert [each.key for each in kept] == [GROUND.key]
    assert whole


# ---------- through search, with the database stood in for ----------

DEFINITIONS = clause("law:art-4", "For the purposes of this Law:", 0)
TERMS = [clause(f"law:art-4:pt-{number}", "t" * 200, 1) for number in range(1, 21)]
OTHERS = [clause(f"law:art-{number}:para-1", "Another rule.", 1) for number in range(10, 20)]
TITLES = {f"law:art-{number}": clause(f"law:art-{number}", "", 0) for number in range(10, 20)}
FOREIGN = [clause(f"other:art-{number}", "A rule of the other law.", 0) for number in range(1, 30)]
EVERY = {each.key: each for each in [DEFINITIONS, *TERMS, *OTHERS, *TITLES.values(), *FOREIGN]}


def above(key: str) -> tuple[ClauseView, ...]:
    if key.startswith("law:art-4:"):
        return (DEFINITIONS,)
    if key.startswith("law:") and key.count(":") == 2:
        return (TITLES[key.rsplit(":", 1)[0]],)
    return ()


def stand_in(monkeypatch: pytest.MonkeyPatch, lists: dict[str | None, list[str]]) -> None:
    from types import SimpleNamespace

    from dpolens.engine.search import engine
    from dpolens.engine.search.keyword import Candidate

    def listed(keys: list[str]) -> list[Candidate]:
        return [
            Candidate(key=key, lang="en", score=1 - rank / 100, rank=rank)
            for rank, key in enumerate(keys, start=1)
        ]

    def law(packs: list[str]) -> str | None:
        return packs[0] if packs else None

    def read(session: object, wanted: list[str], **_: object) -> dict[str, object]:
        return {
            key: SimpleNamespace(clause=EVERY[key], breadcrumb=above(key), cross_references=())
            for key in wanted
        }

    def whole(session: object, key: str, **_: object) -> object:
        beneath = [each for each in EVERY.values() if each.key.startswith(f"{key}:")]
        return SimpleNamespace(
            clause=EVERY[key], breadcrumb=above(key), beneath=beneath, cross_references={}
        )

    monkeypatch.setattr(engine, "keyword_search", lambda *_, **__: [])
    monkeypatch.setattr(
        engine, "vector_search", lambda *_, packs, **__: listed(lists.get(law(packs), []))
    )
    monkeypatch.setattr(engine, "get_clauses", read)
    monkeypatch.setattr(engine, "get_whole", whole)


def rules_found(laws: tuple[str, ...], limit: int) -> list[object]:
    from types import SimpleNamespace

    from dpolens.engine.search import engine

    return engine.search(  # type: ignore[return-value]
        object(),  # type: ignore[arg-type]
        SimpleNamespace(encode_query=lambda query: None),  # type: ignore[arg-type]
        "what counts as a term",
        limit=limit,
        scope=SimpleNamespace(laws=laws, narrowed=True),  # type: ignore[arg-type]
        questions=False,
        rules=True,
    )


# The law's list: two terms, then other rules, with an eighth term between them.
LAW_LIST = [
    "law:art-4:pt-1",
    "law:art-10:para-1",
    "law:art-4:pt-2",
    "law:art-11:para-1",
    "law:art-12:para-1",
    "law:art-13:para-1",
    "law:art-4:pt-8",
    "law:art-14:para-1",
    "law:art-15:para-1",
    "law:art-16:para-1",
]


def test_points_come_back_as_their_rule_in_the_order_their_best_came(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stand_in(monkeypatch, {"law": LAW_LIST})

    found = rules_found(("law",), limit=3)

    assert [result.clause.key for result in found] == [  # type: ignore[attr-defined]
        "law:art-4",
        "law:art-10:para-1",
        "law:art-11:para-1",
    ]
    definitions = found[0]
    assert [each.key for each in definitions.beneath] == [  # type: ignore[attr-defined]
        "law:art-4:pt-1",
        "law:art-4:pt-2",
    ]
    assert not definitions.whole  # type: ignore[attr-defined]


def test_a_long_rule_shows_the_same_clauses_whatever_is_searched_beside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Beside another law, the law fills fewer of the places, and would read less of its list:
    the eighth term, its second best, would be missed. Each source reads as far as it would
    alone."""
    reach = [
        "law:art-4:pt-1",
        "law:art-10:para-1",
        "law:art-11:para-1",
        "law:art-12:para-1",
        "law:art-13:para-1",
        "law:art-4:pt-8",
        "law:art-14:para-1",
    ]
    stand_in(monkeypatch, {"law": reach, "other": [each.key for each in FOREIGN]})

    alone = rules_found(("law",), limit=3)[0]
    beside = next(
        result
        for result in rules_found(("law", "other"), limit=3)
        if result.clause.key == "law:art-4"  # type: ignore[attr-defined]
    )

    assert [each.key for each in alone.beneath] == [  # type: ignore[attr-defined]
        "law:art-4:pt-1",
        "law:art-4:pt-8",
    ]
    assert [each.key for each in beside.beneath] == [  # type: ignore[attr-defined]
        each.key
        for each in alone.beneath  # type: ignore[attr-defined]
    ]
