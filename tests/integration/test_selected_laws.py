"""Which laws apply, and what a search covers because of it.

A search covers the selected laws and the organisation's policies, and nothing else:
not a law outside the selection named on purpose, and, until somebody chooses, no law.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, delete, func, select, text, update
from sqlalchemy.orm import Session

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user
from dpolens.engine.embedding import Embedder, get_model
from dpolens.engine.embedding.index import build_index
from dpolens.engine.evals import Question, run_set
from dpolens.engine.logs.governance import LAWS_SELECTED, Actor
from dpolens.engine.logs.models import GovernanceEntry, QueryLogEntry
from dpolens.engine.packs.load import load_pack
from dpolens.engine.packs.models import Pack, SelectedLaw
from dpolens.engine.packs.selection import (
    EmptySelection,
    NothingSelected,
    NotSelected,
    UnknownLaw,
    newly_arrived,
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
        assert selected_laws(two_laws) is None
        with pytest.raises(NothingSelected, match="nobody has chosen which laws apply") as refused:
            scope_for(two_laws)
        # The dashboard asks at any sign-in while nothing is chosen, and an upgraded
        # instance's first sign-in is long past.
        assert "the next time they sign in to the dashboard" in str(refused.value)

    def test_choosing_narrows_what_a_search_covers(self, two_laws: Session) -> None:
        select_laws(two_laws, ["testlaw"], actor=ACTOR)

        scope = scope_for(two_laws)
        assert scope.laws == ("testlaw",)
        assert scope.narrowed

    def test_an_instance_with_no_law_searches_its_policies(self, session: Session) -> None:
        """There is nothing to choose, so nothing to wait for."""
        scope = scope_for(session)

        assert scope.laws == ()
        assert not scope.narrowed

    def test_a_law_that_is_not_loaded_cannot_be_chosen(self, two_laws: Session) -> None:
        with pytest.raises(UnknownLaw, match="The laws to choose from are: bilingual, testlaw"):
            select_laws(two_laws, ["gdpr"], actor=ACTOR)

        assert selected_laws(two_laws) is None

    def test_a_selection_is_never_empty(self, two_laws: Session) -> None:
        """Once somebody has chosen, some law always applies."""
        with pytest.raises(EmptySelection):
            select_laws(two_laws, [], actor=ACTOR)

    def test_every_change_is_written_to_the_governance_log(self, two_laws: Session) -> None:
        last = two_laws.scalar(select(func.coalesce(func.max(GovernanceEntry.seq), 0)))

        select_laws(two_laws, ["testlaw"], actor=ACTOR)
        select_laws(two_laws, ["testlaw", "bilingual"], actor=ACTOR)

        written = two_laws.scalars(
            select(GovernanceEntry).where(GovernanceEntry.seq > last).order_by(GovernanceEntry.seq)
        ).all()
        assert [
            (entry.action, entry.details.get("before"), entry.details.get("after"))
            for entry in written
        ] == [
            (LAWS_SELECTED, None, ["testlaw"]),
            (LAWS_SELECTED, ["testlaw"], ["bilingual", "testlaw"]),
        ]


class TestWhatASearchCovers:
    def test_until_someone_chooses_nothing_is_searched(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        with pytest.raises(NothingSelected):
            search(two_laws, embedder, BOTH, limit=10)

    def test_a_search_covers_only_the_chosen_law(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        select_laws(two_laws, ["testlaw"], actor=ACTOR)

        found = search(two_laws, embedder, BOTH, limit=10)

        assert laws_of(found) == {"testlaw"}

    def test_naming_one_of_the_chosen_laws_keeps_to_it(
        self, two_laws: Session, embedder: Embedder
    ) -> None:
        select_laws(two_laws, ["testlaw", "bilingual"], actor=ACTOR)

        found = search(two_laws, embedder, BOTH, limit=10, scope=scope_for(two_laws, ["bilingual"]))

        assert found
        assert laws_of(found) == {"bilingual"}

    def test_a_law_outside_the_selection_is_refused_by_name(self, two_laws: Session) -> None:
        select_laws(two_laws, ["testlaw"], actor=ACTOR)

        with pytest.raises(
            NotSelected, match="bilingual is loaded here but is not one of this organisation's"
        ):
            scope_for(two_laws, ["bilingual"])

    def test_a_law_that_is_not_loaded_is_refused_with_the_organisations_laws(
        self, two_laws: Session
    ) -> None:
        """Never with every loaded law, which would name the ones nobody chose."""
        select_laws(two_laws, ["testlaw"], actor=ACTOR)

        with pytest.raises(UnknownLaw, match=r"The laws to choose from are: testlaw$"):
            scope_for(two_laws, ["gdpr"])

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


@pytest.fixture(scope="module")
def arrivals(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[Engine]:
    """A governance log of its own, since what is new depends on its first choice."""
    _, owner_url = database_of_its_own("dpolens_new_laws")
    owner = create_engine(owner_url)
    yield owner
    owner.dispose()


def test_a_law_that_arrives_after_the_first_choice_is_new_for_30_days(arrivals: Engine) -> None:
    with session_from(arrivals) as opened:
        load_pack(opened, FIXTURE_PACKS / "testlaw")
        load_pack(opened, FIXTURE_PACKS / "bilingual")
    with session_from(arrivals) as opened:
        assert newly_arrived(opened) == frozenset()
        select_laws(opened, ["testlaw"], actor=ACTOR)
    with session_from(arrivals) as opened:
        chosen = opened.scalars(
            select(GovernanceEntry.occurred_at).where(GovernanceEntry.action == LAWS_SELECTED)
        ).one()
        # Set by hand, because the database and this process each keep their own clock.
        opened.execute(
            update(Pack)
            .where(Pack.slug == "testlaw")
            .values(loaded_at=chosen - timedelta(minutes=5))
        )
        opened.execute(
            update(Pack)
            .where(Pack.slug == "bilingual")
            .values(loaded_at=chosen + timedelta(minutes=5))
        )
    with session_from(arrivals) as opened:
        assert newly_arrived(opened) == {"bilingual"}
        later = datetime.now(UTC) + timedelta(days=31)
        assert newly_arrived(opened, now=later) == frozenset()


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
    # Back to nobody having chosen, which no instance returns to but every test starts from.
    with session_from(owner) as opened:
        opened.execute(delete(SelectedLaw))


def latest(owner: Engine) -> tuple[str, str | None]:
    """The newest query log row's status and scope."""
    with session_from(owner) as opened:
        row = opened.execute(
            select(QueryLogEntry.status, QueryLogEntry.scope)
            .order_by(QueryLogEntry.created_at.desc())
            .limit(1)
        ).one()
        return row.status, row.scope


class TestOverHttp:
    def test_before_anybody_chooses_a_search_is_refused(self, api: TestClient) -> None:
        response = api.post("/v1/search", json={"query": BOTH})

        assert response.status_code == 409
        assert response.json()["type"] == "/problems/no-laws-selected"
        assert "dpolens init" in response.json()["detail"]

    def test_the_default_covers_the_selection_and_is_logged_as_inside_it(
        self, api: TestClient, testlaw_selected: Engine
    ) -> None:
        response = api.post("/v1/search", json={"query": BOTH})

        assert response.status_code == 200, response.text
        found = response.json()
        assert found["laws"] == ["testlaw"]
        assert found["results"]
        assert all("in_selected_laws" not in result for result in found["results"])
        assert latest(testlaw_selected) == ("ok", "selected")

    def test_a_law_outside_the_selection_is_refused_by_name(
        self, api: TestClient, testlaw_selected: Engine
    ) -> None:
        response = api.post("/v1/search", json={"query": BOTH, "laws": ["bilingual"]})

        assert response.status_code == 403
        refused = response.json()
        assert refused["type"] == "/problems/law-not-selected"
        assert refused["laws"] == ["bilingual"]
        assert refused["detail"] == (
            "bilingual is loaded here but is not one of this organisation's laws. "
            "An administrator can add it in Selected laws."
        )

    def test_a_law_that_is_not_loaded_is_refused_with_the_organisations_laws(
        self, api: TestClient, testlaw_selected: Engine
    ) -> None:
        response = api.post("/v1/search", json={"query": BOTH, "laws": ["gdpr"]})

        assert response.status_code == 422
        assert response.json()["type"] == "/problems/unknown-law"
        assert response.json()["laws"] == ["testlaw"]

    def test_the_library_lists_only_the_organisations_laws(
        self, api: TestClient, testlaw_selected: Engine
    ) -> None:
        response = api.get("/v1/documents")

        assert response.status_code == 200, response.text
        documents = response.json()["documents"]
        assert {document["pack_slug"] for document in documents} == {"testlaw"}
        assert response.json()["total"] == len(documents)
        assert all(document["in_selected_laws"] for document in documents)

    @pytest.mark.parametrize(
        "path",
        [
            "/v1/documents/bilingual",
            "/v1/clauses/bilingual:art-1",
            "/v1/clauses/bilingual:art-1/subtree",
        ],
    )
    def test_a_token_cannot_read_a_law_outside_the_selection(
        self, api: TestClient, testlaw_selected: Engine, path: str
    ) -> None:
        response = api.get(path)

        assert response.status_code == 403
        assert response.json()["type"] == "/problems/law-not-selected"
        assert latest(testlaw_selected)[0] == "refused"

    def test_a_token_reads_a_chosen_law_with_its_clause_marked_as_inside(
        self, api: TestClient, testlaw_selected: Engine
    ) -> None:
        response = api.get("/v1/clauses/testlaw:art-5")

        assert response.status_code == 200, response.text
        assert response.json()["in_selected_laws"] is True

    def test_before_anybody_chooses_a_token_reads_no_law(self, api: TestClient) -> None:
        response = api.get("/v1/clauses/testlaw:art-5")

        assert response.status_code == 409
        assert response.json()["type"] == "/problems/no-laws-selected"
