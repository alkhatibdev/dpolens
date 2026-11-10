"""Search questions at the database: loaded beside their clauses, and used only to reorder the
clauses that have them, never once those clauses' words change, never on another day, and never
when an organisation has turned them off.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, timedelta
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
from dpolens.engine.search import SearchResult, search
from dpolens.engine.search.questions import (
    QuestionsError,
    current_fingerprints,
    embed_questions,
    load_questions,
    questions_on,
    switch_questions,
)

pytestmark = pytest.mark.integration

ARABIC = re.compile(r"[؀-ۿ]")
# Asked in Arabic of a law written in English, so keyword search finds nothing and meaning
# search, where a question counts, decides the order: the case the questions help most.
QUERY = "سحب أحد المستخدمين موافقته. هل يجب أن نحذف بياناته؟"
WITHDRAWN = "testlaw:art-5:para-1"
EXCEPTION = "testlaw:art-5:para-2"
CARDS = {EXCEPTION: [QUERY], WITHDRAWN: ["هل يمكن للمستخدم أن يغير رأيه لاحقاً؟"]}


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


def test_a_question_moves_its_clause_up_among_the_clauses_that_have_them(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    loaded(indexed, embedder, written(tmp_path, indexed, CARDS))

    plain = keys(search(indexed, embedder, QUERY, questions=False))
    asked = keys(search(indexed, embedder, QUERY, questions=True))

    assert plain.index(WITHDRAWN) < plain.index(EXCEPTION)
    assert asked.index(EXCEPTION) < asked.index(WITHDRAWN)


def test_a_clause_without_questions_keeps_its_place(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    """A question measures closer to a question than a clause's words do, so a clause without
    any, such as a policy's, would sink below every clause with them if they took its place."""
    loaded(indexed, embedder, written(tmp_path, indexed, CARDS))

    plain = keys(search(indexed, embedder, QUERY, questions=False))
    asked = keys(search(indexed, embedder, QUERY, questions=True))

    def without_cards(found: list[str]) -> list[str | None]:
        return [None if key in CARDS else key for key in found]

    assert without_cards(asked) == without_cards(plain)
    assert set(asked) == set(plain)


def test_questions_whose_clause_changed_are_not_used(
    indexed: Session, embedder: Embedder, tmp_path: Path
) -> None:
    load_questions(indexed, written(tmp_path, indexed, CARDS, stale=[EXCEPTION]), actor=cli_actor())
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
