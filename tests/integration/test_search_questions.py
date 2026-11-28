"""Search questions at the database: loaded beside their clauses, a list of their own in their
law's ranking, and words keyword search reads beside the clause's; never once those clauses'
words change, never on another day, and never when an organisation has turned them off.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.embedding import Embedder, get_model
from dpolens.engine.embedding.index import build_index
from dpolens.engine.logs.governance import (
    SEARCH_QUESTIONS_LOADED,
    SEARCH_QUESTIONS_SWITCHED,
    cli_actor,
)
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.packs.load import load_pack
from dpolens.engine.packs.selection import select_laws
from dpolens.engine.search import SearchResult, keyword_search, search
from dpolens.engine.search.keyword import quoted
from dpolens.engine.search.questions import (
    QuestionsError,
    current_fingerprints,
    embed_questions,
    load_questions,
    questions_on,
    switch_questions,
    without_questions,
    write_keyword_texts,
)

pytestmark = pytest.mark.integration

ARABIC = re.compile(r"[؀-ۿ]")
# Asked in Arabic of a law written in English, so keyword search finds nothing and meaning
# search, where a question counts, decides the order: the case the questions help most.
QUERY = "سحب أحد المستخدمين موافقته. هل يجب أن نحذف بياناته؟"
WITHDRAWN = "testlaw:art-5:para-1"
EXCEPTION = "testlaw:art-5:para-2"
CARDS = {EXCEPTION: [QUERY], WITHDRAWN: ["هل يمكن للمستخدم أن يغير رأيه لاحقاً؟"]}
RULES = [
    "testlaw:art-5",
    "testlaw:art-5:para-1",
    "testlaw:art-5:para-1:pt-a",
    "testlaw:art-5:para-1:pt-b",
    "testlaw:art-5:para-2",
    "testlaw:art-6:para-1",
]
"""The test law's clauses that state a rule in words: not Article 6's heading, which has none,
and not the recital, which explains without obliging."""


@pytest.fixture(scope="session")
def embedder() -> Iterator[Embedder]:
    with Embedder(get_model("e5-small")) as loaded:
        yield loaded


@pytest.fixture
def indexed(session: Session, testlaw_pack: Path, embedder: Embedder) -> Session:
    load_pack(session, testlaw_pack)
    select_laws(session, ["testlaw"], actor=cli_actor())
    session.commit()
    build_index(session, embedder)
    session.commit()
    return session


def written(
    folder: Path,
    session: Session,
    cards: Mapping[str, Sequence[str]],
    stale: Sequence[str] = (),
    pack: str = "testlaw",
) -> Path:
    """A law's file of questions, each beside the words its clause holds now, unless stale."""
    prints = current_fingerprints(session, list(cards))
    path = folder / f"{pack}.yaml"
    body = {
        "pack": pack,
        "written_by": ["a writer"],
        "checked_by": ["a checker"],
        "written_on": "2026-11-08",
        "write_prompt": "0" * 16,
        "check_prompt": "1" * 16,
        "clauses": [
            {
                "key": key,
                "text": "f" * 16 if key in stale else prints.get(key, "f" * 16),
                "en": [question for question in questions if not ARABIC.search(question)],
                "ar": [question for question in questions if ARABIC.search(question)],
            }
            for key, questions in cards.items()
        ],
    }
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return path


def loaded(session: Session, embedder: Embedder, path: Path) -> None:
    load_questions(session, path, actor=cli_actor())
    embed_questions(session, embedder)
    session.commit()


def keys(results: Sequence[SearchResult]) -> list[str]:
    return [result.clause.key for result in results]


def entries(session: Session, action: str) -> list[GovernanceEntry]:
    """The log's entries of one kind, oldest first: the log is append-only, so a test reads
    the ones written after it started."""
    return list(
        session.scalars(
            select(GovernanceEntry)
            .where(GovernanceEntry.action == action)
            .order_by(GovernanceEntry.seq)
        )
    )


@pytest.fixture
def two_laws(
    session: Session, testlaw_pack: Path, bilingual_pack: Path, embedder: Embedder
) -> Session:
    load_pack(session, testlaw_pack)
    load_pack(session, bilingual_pack)
    select_laws(session, ["testlaw", "bilingual"], actor=cli_actor())
    session.commit()
    build_index(session, embedder)
    session.commit()
    return session


def test_a_close_question_moves_its_clause_up(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    loaded(indexed, embedder, written(tmp_path, indexed, CARDS))

    plain = keys(search(indexed, embedder, QUERY, questions=False))
    asked = keys(search(indexed, embedder, QUERY, questions=True))

    assert plain.index(WITHDRAWN) < plain.index(EXCEPTION)
    assert asked.index(EXCEPTION) < plain.index(EXCEPTION)


def test_a_law_without_questions_keeps_its_turns_beside_one_with_them(
    two_laws: Session, embedder: Embedder, tmp_path: Path
) -> None:
    """A question resembles a question more than legal text, so a law's questions score above
    any clause's own words. In one list, a law without them would sink below the one with them.
    Each law is ranked by itself, and the laws take turns."""
    loaded(two_laws, embedder, written(tmp_path, two_laws, CARDS))

    found = keys(search(two_laws, embedder, "Can a user withdraw consent?", questions=True))
    laws = [key.split(":")[0] for key in found]

    shared = 2 * min(laws.count("testlaw"), laws.count("bilingual"))
    assert shared >= 4
    assert all(one != other for one, other in pairwise(laws[:shared]))


def test_keyword_search_reads_a_law_s_questions_after_its_words(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    """The test law has no Arabic words, so an Arabic question finds nothing in them by keyword.
    Its Arabic questions are words of their own beside the clause they were written for."""
    loaded(indexed, embedder, written(tmp_path, indexed, CARDS))

    alone = keyword_search(indexed, QUERY, lang="ar", packs=["testlaw"])
    asked = keyword_search(indexed, QUERY, lang="ar", packs=["testlaw"], with_questions=True)

    assert alone == []
    assert [candidate.key for candidate in asked][:1] == [EXCEPTION]
    ranked = {result.clause.key: result.ranks for result in search(indexed, embedder, QUERY)}
    assert "keyword" in ranked[EXCEPTION]
    assert "questions" in ranked[EXCEPTION]


def test_writing_the_keyword_words_again_scores_every_clause_the_same(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    """They are written again each time the questions or a law change. A BM25 index counts a
    deleted row until it is rebuilt, so rows deleted and written again would drift."""
    loaded(indexed, embedder, written(tmp_path, indexed, CARDS))
    asked = "consent withdrawn erase the data"
    before = keyword_search(indexed, asked, packs=["testlaw"], with_questions=True)

    for _ in range(3):
        write_keyword_texts(indexed)
    after = keyword_search(indexed, asked, packs=["testlaw"], with_questions=True)

    assert before
    assert after == before


def test_a_question_repeating_a_clause_s_own_words_quotes_it(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    """Its own words, never its questions': a question can repeat a search question's words
    and still be asking in everyday words."""
    near_quote = "the controller shall erase personal data without undue delay where grounds apply"
    loaded(
        indexed,
        embedder,
        written(tmp_path, indexed, {"testlaw:art-6:para-1": [near_quote], EXCEPTION: [QUERY]}),
    )
    candidates = ["testlaw:art-6:para-1", "testlaw:art-5"]

    assert quoted(indexed, near_quote, "en", candidates) == "testlaw:art-5"
    assert quoted(indexed, near_quote, "en", ["testlaw:art-6:para-1"]) is None
    assert quoted(indexed, "erase personal data", "en", candidates) is None, "too few words"
    assert keys(search(indexed, embedder, near_quote))[:1] == ["testlaw:art-5"]


def test_a_law_is_searchable_by_its_words_as_soon_as_it_is_loaded(
    session: Session, testlaw_pack: Path
) -> None:
    load_pack(session, testlaw_pack)

    found = keyword_search(session, "erase personal data", packs=["testlaw"], with_questions=True)

    assert "testlaw:art-5" in [candidate.key for candidate in found]


def test_questions_whose_clause_changed_are_not_used(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    load_questions(indexed, written(tmp_path, indexed, CARDS, stale=list(CARDS)), actor=cli_actor())
    embed_questions(indexed, embedder)
    indexed.commit()

    assert keys(search(indexed, embedder, QUERY, questions=True)) == keys(
        search(indexed, embedder, QUERY, questions=False)
    )


def test_a_search_of_another_day_goes_without_them(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    loaded(indexed, embedder, written(tmp_path, indexed, CARDS))
    yesterday = date.today() - timedelta(days=1)

    assert keys(search(indexed, embedder, QUERY, as_of=yesterday, questions=True)) == keys(
        search(indexed, embedder, QUERY, as_of=yesterday, questions=False)
    )


def test_turned_off_a_search_goes_without_them_and_the_log_says_who(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    loaded(indexed, embedder, written(tmp_path, indexed, CARDS))
    assert questions_on(indexed)
    before = len(entries(indexed, SEARCH_QUESTIONS_SWITCHED))

    switch_questions(indexed, False, actor=cli_actor())
    switch_questions(indexed, False, actor=cli_actor())
    indexed.commit()

    assert not questions_on(indexed)
    assert keys(search(indexed, embedder, QUERY)) == keys(
        search(indexed, embedder, QUERY, questions=False)
    )
    switched = entries(indexed, SEARCH_QUESTIONS_SWITCHED)[before:]
    assert [(entry.details["before"], entry.details["after"]) for entry in switched] == [
        (True, False)
    ]
    assert switched[0].details["via"] == "cli"


def test_loading_is_logged_once_and_the_same_file_again_changes_nothing(
    indexed: Session, tmp_path: Path
) -> None:
    path = written(tmp_path, indexed, CARDS)
    before = len(entries(indexed, SEARCH_QUESTIONS_LOADED))

    first = load_questions(indexed, path, actor=cli_actor())
    second = load_questions(indexed, path, actor=cli_actor())

    assert (first.questions, first.current, first.unchanged) == (2, 2, False)
    assert (second.questions, second.current, second.unchanged) == (2, 2, True)
    [logged] = entries(indexed, SEARCH_QUESTIONS_LOADED)[before:]
    assert logged.target_id == "testlaw"
    assert logged.details["questions"] == 2


def test_a_newer_file_replaces_the_questions_a_law_had(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    loaded(indexed, embedder, written(tmp_path, indexed, CARDS))

    replaced = load_questions(
        indexed,
        written(tmp_path, indexed, {WITHDRAWN: ["Can a user change their mind?"]}),
        actor=cli_actor(),
    )

    assert (replaced.questions, replaced.unchanged) == (1, False)
    assert embed_questions(indexed, embedder) == 1


def test_each_question_is_embedded_once(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    load_questions(indexed, written(tmp_path, indexed, CARDS), actor=cli_actor())

    assert embed_questions(indexed, embedder) == 2
    assert embed_questions(indexed, embedder) == 0


def test_a_file_for_a_law_that_is_not_loaded_is_refused(indexed: Session, tmp_path: Path) -> None:
    path = written(tmp_path, indexed, {"elsewhere:art-1": ["Anything?"]}, pack="elsewhere")

    with pytest.raises(QuestionsError, match="elsewhere is not loaded here"):
        load_questions(indexed, path, actor=cli_actor())


def test_a_file_holding_another_laws_clauses_is_refused(indexed: Session, tmp_path: Path) -> None:
    path = written(tmp_path, indexed, {"otherlaw:art-1": ["Anything?"]})

    with pytest.raises(QuestionsError, match="another law's clauses: otherlaw:art-1"):
        load_questions(indexed, path, actor=cli_actor())


def test_status_names_each_clause_that_states_a_rule_and_has_no_questions(
    indexed: Session, tmp_path: Path
) -> None:
    load_questions(indexed, written(tmp_path, indexed, CARDS), actor=cli_actor())

    assert without_questions(indexed) == {"testlaw": [key for key in RULES if key not in CARDS]}


def test_a_clause_named_with_no_questions_was_written_for(indexed: Session, tmp_path: Path) -> None:
    """Its check kept none of them, and the file says so rather than leaving it out."""
    every = {key: CARDS.get(key, []) for key in RULES}

    loaded = load_questions(indexed, written(tmp_path, indexed, every), actor=cli_actor())

    assert loaded.questions == 2
    assert without_questions(indexed) == {}


def test_a_clause_whose_words_changed_since_is_named(indexed: Session, tmp_path: Path) -> None:
    every = {key: CARDS.get(key, []) for key in RULES}

    load_questions(indexed, written(tmp_path, indexed, every, stale=[EXCEPTION]), actor=cli_actor())

    assert without_questions(indexed) == {"testlaw": [EXCEPTION]}


def test_a_law_without_a_file_is_not_held_to_one(indexed: Session) -> None:
    """Its clauses are found by their own words, ranked by themselves."""
    assert without_questions(indexed) == {}


def test_a_newer_file_names_its_own_clauses(indexed: Session, tmp_path: Path) -> None:
    load_questions(
        indexed, written(tmp_path, indexed, {key: [] for key in RULES}), actor=cli_actor()
    )

    load_questions(indexed, written(tmp_path, indexed, CARDS), actor=cli_actor())

    assert without_questions(indexed) == {"testlaw": [key for key in RULES if key not in CARDS]}


def test_a_file_naming_a_clause_twice_is_refused(indexed: Session, tmp_path: Path) -> None:
    path = written(tmp_path, indexed, CARDS)
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    body["clauses"].append(body["clauses"][0])
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")

    with pytest.raises(QuestionsError, match=f"names {EXCEPTION} twice"):
        load_questions(indexed, path, actor=cli_actor())


def test_a_file_with_a_clause_and_no_fingerprint_is_refused(
    indexed: Session, tmp_path: Path
) -> None:
    path = written(tmp_path, indexed, CARDS)
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    del body["clauses"][0]["text"]
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")

    with pytest.raises(QuestionsError, match="a clause without its key or its text"):
        load_questions(indexed, path, actor=cli_actor())
