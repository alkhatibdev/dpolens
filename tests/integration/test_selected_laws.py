"""Which laws apply, and what a search covers because of it.

The default matters most: until somebody chooses, a search covers every loaded law,
exactly as it did before there was anything to choose.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user
from dpolens.engine.embedding import Embedder, get_model
from dpolens.engine.embedding.index import build_index
from dpolens.engine.evals import Question, run_set
from dpolens.engine.logs.governance import LAWS_SELECTED, LAWS_SELECTION_CLEARED, Actor
from dpolens.engine.logs.models import GovernanceEntry, QueryLogEntry
from dpolens.engine.packs.load import load_pack
from dpolens.engine.packs.selection import (
    EmptySelection,
    UnknownLaw,
    clear_selection,
    scope_for,
    select_laws,
    selected_laws,
)
from dpolens.engine.search import SearchResult, keyword_search, search, vector_search
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
BOTH = "personal data"
"""A question both fixture laws answer, in their English texts."""


@pytest.fixture(scope="session")
def embedder() -> Iterator[Embedder]:
    with Embedder(get_model("e5-small")) as loaded:
        yield loaded


@pytest.fixture
def two_laws(
    session: Session, testlaw_pack: Path, bilingual_pack: Path, embedder: Embedder
) -> Session:
    load_pack(session, testlaw_pack)
    load_pack(session, bilingual_pack)
    session.commit()
    build_index(session, embedder)
    session.commit()
    return session


def laws_of(results: Sequence[SearchResult]) -> set[str | None]:
    return {result.clause.pack_slug for result in results}


class TestTheSelection:
    def test_nobody_has_chosen_until_someone_does(self, two_laws: Session) -> None:
        scope = scope_for(two_laws)

        assert selected_laws(two_laws) is None
        assert scope.laws == ("bilingual", "testlaw")
        assert not scope.narrowed
        assert not scope.outside_selection

    def test_choosing_narrows_what_a_search_covers(self, two_laws: Session) -> None:
        select_laws(two_laws, ["testlaw"], actor=ACTOR)

        scope = scope_for(two_laws)
        assert scope.laws == ("testlaw",)
        assert scope.narrowed

    def test_a_law_that_is_not_loaded_cannot_be_chosen(self, two_laws: Session) -> None:
        with pytest.raises(UnknownLaw, match="The loaded laws are: bilingual, testlaw"):
            select_laws(two_laws, ["gdpr"], actor=ACTOR)

        assert selected_laws(two_laws) is None

    def test_a_selection_is_never_empty(self, two_laws: Session) -> None:
        """Clearing is how to go back to every law, so "nobody chose" means one thing."""
        with pytest.raises(EmptySelection):
            select_laws(two_laws, [], actor=ACTOR)

    def test_every_change_is_written_to_the_governance_log(self, two_laws: Session) -> None:
        last = two_laws.scalar(select(func.coalesce(func.max(GovernanceEntry.seq), 0)))

        select_laws(two_laws, ["testlaw"], actor=ACTOR)
        select_laws(two_laws, ["testlaw", "bilingual"], actor=ACTOR)
        clear_selection(two_laws, actor=ACTOR)
        clear_selection(two_laws, actor=ACTOR)

        written = two_laws.scalars(
            select(GovernanceEntry).where(GovernanceEntry.seq > last).order_by(GovernanceEntry.seq)
        ).all()
        assert [
            (entry.action, entry.details.get("before"), entry.details.get("after"))
            for entry in written
        ] == [
            (LAWS_SELECTED, None, ["testlaw"]),
            (LAWS_SELECTED, ["testlaw"], ["bilingual", "testlaw"]),
            # The second clear had nothing to clear, so it wrote nothing.
            (LAWS_SELECTION_CLEARED, ["bilingual", "testlaw"], None),
        ]


class TestWhatASearchCovers:
    def test_until_someone_chooses_every_law_is_searched(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        found = search(two_laws, embedder, BOTH, limit=10)

        assert laws_of(found) == {"bilingual", "testlaw"}
        assert all(result.in_selected_laws for result in found)

    def test_a_search_covers_only_the_chosen_law(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        select_laws(two_laws, ["testlaw"], actor=ACTOR)

        found = search(two_laws, embedder, BOTH, limit=10)

        assert laws_of(found) == {"testlaw"}

    def test_another_law_is_reached_by_naming_it_and_comes_back_marked(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        select_laws(two_laws, ["testlaw"], actor=ACTOR)
        scope = scope_for(two_laws, ["bilingual"])

        found = search(two_laws, embedder, BOTH, limit=10, scope=scope)

        assert scope.outside_selection
        assert found
        assert laws_of(found) == {"bilingual"}
        assert not any(result.in_selected_laws for result in found)

    def test_both_retrievers_keep_to_the_laws_they_are_given(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        keyword = keyword_search(two_laws, BOTH, lang="en", packs=["bilingual"])
        meaning = vector_search(two_laws, embedder, BOTH, packs=["bilingual"])

        assert keyword
        assert meaning
        assert {candidate.key.split(":")[0] for candidate in keyword} == {"bilingual"}
        assert {candidate.key.split(":")[0] for candidate in meaning} == {"bilingual"}

    def test_a_kept_search_does_not_keep_the_next_one(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        """SET LOCAL lasts for the transaction, so each search sets the scan its own way."""
        vector_search(two_laws, embedder, BOTH, packs=["bilingual"])
        assert two_laws.execute(text("SHOW hnsw.iterative_scan")).scalar() == "strict_order"

        vector_search(two_laws, embedder, BOTH)
        assert two_laws.execute(text("SHOW hnsw.iterative_scan")).scalar() == "off"

    def test_an_eval_run_searches_only_the_law_it_tests(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        """Whatever is selected, so that a score means that law."""
        select_laws(two_laws, ["bilingual"], actor=ACTOR)
        question = Question(
            id="both",
            question=BOTH,
            lang="en",
            expected_keys=("testlaw:art-5",),
            source="https://example.com/guidance",
        )

        run = run_set(two_laws, embedder, [question], "rrf:10", pack="testlaw")

        # The testlaw pack holds two documents, the law and its recitals.
        returned = run.outcomes[0].returned
        assert returned
        assert {key.split(":")[0] for key in returned} <= {"testlaw", "testlaw-recitals"}


FIXTURE_PACKS = Path(__file__).parents[1] / "fixtures" / "packs"


@pytest.fixture(scope="module")
def own_instance(
    database_of_its_own: Callable[[str], tuple[str, str]], embedder: Embedder
) -> Iterator[tuple[str, Engine]]:
    """Both laws in a database of their own, since the token minted here can never
    be deleted, and another module's tests count tokens."""
    app_url, owner_url = database_of_its_own("dpolens_selected_laws")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, FIXTURE_PACKS / "testlaw")
        load_pack(opened, FIXTURE_PACKS / "bilingual")
    with session_from(owner) as opened:
        build_index(opened, embedder)
    yield app_url, owner
    owner.dispose()


@pytest.fixture(scope="module")
def api(own_instance: tuple[str, Engine]) -> Iterator[TestClient]:
    app_url, owner = own_instance
    with session_from(owner) as opened:
        create_user(
            opened,
            email="laws@example.com",
            display_name="Reader",
            actor=ACTOR,
            roles=(catalog.DEVELOPER,),
        )
        opened.flush()
        _, token = mint(
            opened,
            email="laws@example.com",
            name="laws",
            permissions=(catalog.DOCUMENTS_READ,),
            actor=ACTOR,
        )
    app = create_app(Settings.model_validate({"database_url": app_url}))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


@pytest.fixture
def testlaw_selected(own_instance: tuple[str, Engine]) -> Iterator[Engine]:
    _, owner = own_instance
    with session_from(owner) as opened:
        select_laws(opened, ["testlaw"], actor=ACTOR)
    yield owner
    with session_from(owner) as opened:
        clear_selection(opened, actor=ACTOR)


def latest_scope(owner: Engine) -> str | None:
    with session_from(owner) as opened:
        return opened.scalar(
            select(QueryLogEntry.scope).order_by(QueryLogEntry.created_at.desc()).limit(1)
        )


class TestOverHttp:
    def test_the_default_covers_the_selection_and_is_logged_as_inside_it(
        self, api: TestClient, testlaw_selected: Engine
    ) -> None:
        response = api.post("/v1/search", json={"query": BOTH})

        assert response.status_code == 200, response.text
        assert response.json()["laws"] == ["testlaw"]
        assert all(result["in_selected_laws"] for result in response.json()["results"])
        assert latest_scope(testlaw_selected) == "selected"

    def test_a_law_outside_the_selection_is_marked_and_logged_as_other(
        self, api: TestClient, testlaw_selected: Engine
    ) -> None:
        response = api.post("/v1/search", json={"query": BOTH, "laws": ["bilingual"]})

        assert response.status_code == 200, response.text
        found = response.json()
        assert found["laws"] == ["bilingual"]
        assert found["results"]
        assert not any(result["in_selected_laws"] for result in found["results"])
        assert latest_scope(testlaw_selected) == "other"

    def test_a_law_that_is_not_loaded_is_refused_with_the_loaded_ones(
        self, api: TestClient
    ) -> None:
        response = api.post("/v1/search", json={"query": BOTH, "laws": ["gdpr"]})

        assert response.status_code == 422
        assert response.json()["type"] == "/problems/unknown-law"
        assert response.json()["laws"] == ["bilingual", "testlaw"]
