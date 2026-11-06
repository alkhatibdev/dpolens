"""An article's first paragraph, returned after a later one.

The retrievers are replaced by lists each test chooses, so what is asserted is where search
places what they found, whatever a model would rank first. Which questions that helps is
measured by the evals.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import dpolens.engine.search.engine as engine
from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user
from dpolens.engine.embedding import Embedder
from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.originals import Directory
from dpolens.engine.packs.load import load_pack
from dpolens.engine.packs.selection import select_laws
from dpolens.engine.policies.store import SAMPLE_SLUG, load_sample
from dpolens.engine.search import SearchResult, search
from dpolens.engine.search.keyword import Candidate
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

Found = Callable[..., None]

ENDED = """    commencement:
      - until: 2026-06-01
        keys: [paragraphs:art-1:para-1]
        source: Repealing Act 2025, section 3
"""


@pytest.fixture
def loaded(session: Session, paragraphs_pack: Path) -> Session:
    load_pack(session, paragraphs_pack)
    select_laws(session, ["paragraphs"], actor=cli_actor())
    session.commit()
    return session


@pytest.fixture
def found(monkeypatch: pytest.MonkeyPatch) -> Found:
    """Meaning search returns these keys, best first, and keyword search returns nothing."""

    def choose(*keys: str) -> None:
        candidates = [
            Candidate(key=key, lang="en", score=1.0 - at / 10, rank=at + 1)
            for at, key in enumerate(keys)
        ]

        def meaning(*args: Any, **kwargs: Any) -> list[Candidate]:
            return candidates

        def keyword(*args: Any, **kwargs: Any) -> list[Candidate]:
            return []

        monkeypatch.setattr(engine, "vector_search", meaning)
        monkeypatch.setattr(engine, "keyword_search", keyword)

    return choose


def searched(session: Session, limit: int = 10) -> list[SearchResult]:
    # The retrievers are replaced, so no model is loaded and none is used.
    return search(session, cast(Embedder, None), "a question", limit=limit, lang="en")


def placed(session: Session, limit: int = 10) -> list[tuple[str, str | None]]:
    return [(result.clause.key, result.returned_with) for result in searched(session, limit)]


def test_a_later_paragraph_is_followed_by_its_articles_first(loaded: Session, found: Found) -> None:
    found("paragraphs:art-1:para-3", "paragraphs:art-2:para-2")

    assert placed(loaded) == [
        ("paragraphs:art-1:para-3", None),
        ("paragraphs:art-1:para-1", "paragraphs:art-1:para-3"),
        ("paragraphs:art-2:para-2", None),
    ]


def test_the_first_paragraph_takes_the_score_of_the_result_it_follows(
    loaded: Session, found: Found
) -> None:
    """So the list still reads best first."""
    found("paragraphs:art-1:para-3", "paragraphs:art-2:para-2")

    scores = [result.score for result in searched(loaded)]

    assert scores[0] == scores[1]
    assert scores == sorted(scores, reverse=True)


def test_a_first_paragraph_neither_retriever_found_has_no_ranks(
    loaded: Session, found: Found
) -> None:
    found("paragraphs:art-1:para-3")

    first = searched(loaded)[1]

    assert first.clause.key == "paragraphs:art-1:para-1"
    assert first.ranks == {}


def test_a_point_of_a_later_paragraph_is_followed_too(loaded: Session, found: Found) -> None:
    found("paragraphs:art-1:para-2:pt-b")

    assert placed(loaded) == [
        ("paragraphs:art-1:para-2:pt-b", None),
        ("paragraphs:art-1:para-1", "paragraphs:art-1:para-2:pt-b"),
    ]


def test_nothing_follows_the_first_paragraph_or_an_article_of_no_paragraph(
    loaded: Session, found: Found
) -> None:
    found("paragraphs:art-1:para-1", "paragraphs:art-2")

    assert placed(loaded) == [("paragraphs:art-1:para-1", None), ("paragraphs:art-2", None)]


def test_nothing_follows_a_paragraph_of_an_article_with_words_of_its_own(
    loaded: Session, found: Found
) -> None:
    """Its paragraphs are the duties its words introduce, and the first is only one of them."""
    found("paragraphs:art-2:para-2")

    assert placed(loaded) == [("paragraphs:art-2:para-2", None)]


def test_a_first_paragraph_found_lower_comes_up_and_is_not_repeated(
    loaded: Session, found: Found
) -> None:
    found("paragraphs:art-1:para-3", "paragraphs:art-2:para-1", "paragraphs:art-1:para-1")

    results = searched(loaded)

    assert [(r.clause.key, r.returned_with) for r in results] == [
        ("paragraphs:art-1:para-3", None),
        ("paragraphs:art-1:para-1", "paragraphs:art-1:para-3"),
        ("paragraphs:art-2:para-1", None),
    ]
    # Where the retriever placed it is still said.
    assert results[1].ranks == {"meaning": 3}


def test_a_first_paragraph_already_above_stays_where_it_is(loaded: Session, found: Found) -> None:
    found("paragraphs:art-1:para-1", "paragraphs:art-1:para-3")

    assert placed(loaded) == [("paragraphs:art-1:para-1", None), ("paragraphs:art-1:para-3", None)]


def test_the_limit_still_holds(loaded: Session, found: Found) -> None:
    found("paragraphs:art-1:para-3", "paragraphs:art-2:para-2", "paragraphs:art-1:para-2")

    assert placed(loaded, limit=1) == [("paragraphs:art-1:para-3", None)]
    assert placed(loaded, limit=2) == [
        ("paragraphs:art-1:para-3", None),
        ("paragraphs:art-1:para-1", "paragraphs:art-1:para-3"),
    ]


def test_a_first_paragraph_a_law_has_ended_is_not_returned(
    session: Session, paragraphs_pack: Path, tmp_path: Path, found: Found
) -> None:
    pack = Path(shutil.copytree(paragraphs_pack, tmp_path / "paragraphs"))
    metadata = pack / "pack.yaml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            "    expected_clauses: 2\n", "    expected_clauses: 2\n" + ENDED, 1
        ),
        encoding="utf-8",
    )
    load_pack(session, pack)
    select_laws(session, ["paragraphs"], actor=cli_actor())
    session.commit()
    found("paragraphs:art-1:para-3")

    assert placed(session) == [("paragraphs:art-1:para-3", None)]


def test_a_policy_is_left_as_it_is(loaded: Session, found: Found, tmp_path: Path) -> None:
    """A policy's sections follow no drafting convention, so its first paragraph is no rule."""
    load_sample(loaded, Directory(tmp_path), actor=cli_actor())
    loaded.commit()
    # Shaped as an article of numbered paragraphs would be: a section with no words of its
    # own above 5.1 and 5.2, so only being a policy keeps 5.1 from following 5.2.
    shape = loaded.execute(
        text(
            """
            SELECT n.node_type, p.node_type AS parent_type,
                   (SELECT count(*) FROM node_texts t
                    WHERE t.node_id = p.id AND length(trim(t.body_text)) > 0) AS parent_texts
            FROM document_nodes n JOIN document_nodes p ON p.id = n.parent_node_id
            WHERE n.canonical_key = :key
            """
        ),
        {"key": f"{SAMPLE_SLUG}:5.2"},
    ).one()
    assert tuple(shape) == ("paragraph", "section", 0)
    found(f"{SAMPLE_SLUG}:5.2")

    assert placed(loaded) == [(f"{SAMPLE_SLUG}:5.2", None)]


def test_the_api_says_which_result_a_first_paragraph_follows(
    database_of_its_own: Callable[[str], tuple[str, str]], paragraphs_pack: Path, found: Found
) -> None:
    app_url, owner_url = database_of_its_own("dpolens_first_paragraph")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=cli_actor())
        load_pack(opened, paragraphs_pack)
        select_laws(opened, ["paragraphs"], actor=cli_actor())
        create_user(
            opened,
            email="first-paragraph@example.com",
            display_name="Reader",
            actor=cli_actor(),
            roles=(catalog.DEVELOPER,),
        )
        opened.flush()
        _, token = mint(
            opened,
            email="first-paragraph@example.com",
            name="first-paragraph",
            permissions=(catalog.DOCUMENTS_READ,),
            actor=cli_actor(),
        )
    owner.dispose()
    found("paragraphs:art-1:para-3", "paragraphs:art-2:para-2")

    app = create_app(Settings.model_validate({"database_url": app_url}))
    with TestClient(app) as client:
        response = client.post(
            "/v1/search",
            json={"query": "a copy of my data"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert [
        (result["clause"]["key"], result["returned_with"]) for result in response.json()["results"]
    ] == [
        ("paragraphs:art-1:para-3", None),
        ("paragraphs:art-1:para-1", "paragraphs:art-1:para-3"),
        ("paragraphs:art-2:para-2", None),
    ]
