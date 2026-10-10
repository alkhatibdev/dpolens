"""The four routes, over a real corpus: what comes back, and what it carries.

The response shape is the contract, so these assert the fields a citation needs
rather than only the status code.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from dpolens.api.app import create_app
from dpolens.api.problems import MEDIA_TYPE
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user
from dpolens.engine.embedding import DEFAULT_MODEL, get_model
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.index import build_index
from dpolens.engine.logs.governance import Actor
from dpolens.engine.packs.load import load_pack
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
TESTLAW = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"


@pytest.fixture(scope="module")
def corpus(committed_owner_url: str) -> Iterator[Engine]:
    """The fixture pack, loaded and indexed once for this module.

    As the owning role, because building a vector index creates one and
    PostgreSQL requires ownership for that. It is maintenance, not serving.
    """
    engine = create_engine(committed_owner_url)
    with session_from(engine) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, TESTLAW)
    with Embedder(get_model(DEFAULT_MODEL)) as embedder, session_from(engine) as opened:
        build_index(opened, embedder)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def api(committed_database_url: str, corpus: Engine) -> Iterator[TestClient]:
    app = create_app(Settings.model_validate({"database_url": committed_database_url}))
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def reader(corpus: Engine) -> str:
    """A token that may read the corpus, and nothing else."""
    email = f"routes-reader-{uuid.uuid4().hex[:8]}@example.com"
    with session_from(corpus) as opened:
        create_user(
            opened,
            email=email,
            display_name="Reader",
            actor=ACTOR,
            roles=(catalog.DEVELOPER,),
        )
        opened.flush()
        _, token = mint(
            opened,
            email=email,
            name="routes",
            permissions=(catalog.DOCUMENTS_READ,),
            actor=ACTOR,
        )
    return token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestSearch:
    def test_a_question_finds_a_clause_with_everything_needed_to_cite_it(
        self, api: TestClient, reader: str
    ) -> None:
        response = api.post(
            "/v1/search", json={"query": "keeping personal data"}, headers=auth(reader)
        )

        assert response.status_code == 200
        results = response.json()["results"]
        assert results
        clause = results[0]["clause"]
        assert clause["key"].startswith("testlaw:")
        assert clause["text"]
        assert clause["document_slug"] == "testlaw"
        assert clause["effective_date"]
        assert clause["version_label"]

    def test_a_result_says_where_the_text_came_from_and_how_far_it_is_checked(
        self, api: TestClient, reader: str
    ) -> None:
        """The field the product's main claim rests on."""
        response = api.post("/v1/search", json={"query": "data"}, headers=auth(reader))

        clause = response.json()["results"][0]["clause"]
        assert clause["pack_slug"] == "testlaw"
        assert clause["trust_tier"] in {"verified", "community"}
        assert clause["jurisdiction"]
        assert clause["source_url"]

    def test_the_fusion_internals_are_absent_unless_asked_for(
        self, api: TestClient, reader: str
    ) -> None:
        """A client that learns to read ranks is a reason not to improve fusion."""
        plain = api.post("/v1/search", json={"query": "data"}, headers=auth(reader))
        assert plain.json()["results"][0]["ranks"] is None

        explained = api.post(
            "/v1/search", json={"query": "data", "explain": True}, headers=auth(reader)
        )
        ranks = explained.json()["results"][0]["ranks"]
        assert set(ranks) <= {"keyword", "meaning"}

    def test_the_fusion_rule_cannot_be_chosen_by_a_client(
        self, api: TestClient, reader: str
    ) -> None:
        """It is a measured default, not a knob, so the field does not exist."""
        response = api.post(
            "/v1/search", json={"query": "data", "fusion": "rrf:60"}, headers=auth(reader)
        )

        assert response.status_code == 200
        assert "fusion" not in response.json()

    def test_a_query_longer_than_the_cap_is_refused(self, api: TestClient, reader: str) -> None:
        """Nobody spends this instance's CPU by asking it to embed a megabyte."""
        response = api.post("/v1/search", json={"query": "x" * 1001}, headers=auth(reader))

        assert response.status_code == 422
        assert response.headers["content-type"].startswith(MEDIA_TYPE)
        assert response.json()["type"] == "/problems/invalid-request"

    def test_an_empty_query_is_refused(self, api: TestClient, reader: str) -> None:
        assert api.post("/v1/search", json={"query": ""}, headers=auth(reader)).status_code == 422

    def test_a_language_this_instance_cannot_search_in_is_refused_with_the_ones_it_can(
        self, api: TestClient, reader: str
    ) -> None:
        """Naming the languages that work lets the caller, often a model, ask again."""
        response = api.post(
            "/v1/search", json={"query": "effacement", "lang": "fr"}, headers=auth(reader)
        )

        assert response.status_code == 422
        assert response.json()["type"] == "/problems/unsupported-language"
        assert response.json()["languages"] == ["en"]
        assert "'fr'" in response.json()["detail"]

    def test_a_question_nothing_answers_comes_back_empty_rather_than_wrong(
        self, api: TestClient, reader: str
    ) -> None:
        response = api.post(
            "/v1/search",
            json={"query": "zzzz quantum chromodynamics lunar", "limit": 3},
            headers=auth(reader),
        )

        assert response.status_code == 200
        assert isinstance(response.json()["results"], list)

    def test_a_date_before_the_text_was_in_force_finds_nothing(
        self, api: TestClient, reader: str
    ) -> None:
        response = api.post(
            "/v1/search",
            json={"query": "data", "as_of": str(date(1990, 1, 1))},
            headers=auth(reader),
        )

        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_searching_needs_the_permission(self, api: TestClient, corpus: Engine) -> None:
        with session_from(corpus) as opened:
            email = f"routes-nothing-{uuid.uuid4().hex[:8]}@example.com"
            create_user(opened, email=email, display_name="No permissions", actor=ACTOR)
            opened.flush()
            _, token = mint(opened, email=email, name="empty", permissions=(), actor=ACTOR)

        response = api.post("/v1/search", json={"query": "data"}, headers=auth(token))

        assert response.status_code == 403
        body = response.json()
        assert body["type"] == "/problems/permission-required"
        assert body["permission"] == catalog.DOCUMENTS_READ


class TestClauses:
    def test_a_clause_comes_back_with_its_context(self, api: TestClient, reader: str) -> None:
        found = api.post("/v1/search", json={"query": "data"}, headers=auth(reader)).json()
        key = found["results"][0]["clause"]["key"]

        response = api.get(f"/v1/clauses/{key}", headers=auth(reader))

        assert response.status_code == 200
        body = response.json()
        assert body["clause"]["key"] == key
        assert isinstance(body["breadcrumb"], list)
        assert isinstance(body["children"], list)

    def test_a_key_nobody_has(self, api: TestClient, reader: str) -> None:
        response = api.get("/v1/clauses/testlaw:art-999", headers=auth(reader))

        assert response.status_code == 404
        assert response.headers["content-type"].startswith(MEDIA_TYPE)
        assert response.json()["type"] == "/problems/not-found"

    def test_a_subtree_returns_the_whole_branch_in_order(
        self, api: TestClient, reader: str
    ) -> None:
        listed = api.get("/v1/documents/testlaw", headers=auth(reader)).json()
        top = listed["outline"][0]["key"]

        response = api.get(f"/v1/clauses/{top}/subtree", headers=auth(reader))

        assert response.status_code == 200
        branch = response.json()
        assert branch[0]["key"] == top
        assert all(clause["key"].startswith(top.split(":")[0]) for clause in branch)

    def test_reading_a_clause_needs_a_token(self, api: TestClient) -> None:
        assert api.get("/v1/clauses/testlaw:art-1").status_code == 401


class TestDocuments:
    def test_the_corpus_lists_what_can_be_cited_today(self, api: TestClient, reader: str) -> None:
        response = api.get("/v1/documents", headers=auth(reader))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert body["limit"] == 50
        assert body["offset"] == 0
        document = next(row for row in body["documents"] if row["slug"] == "testlaw")
        assert document["clauses"] > 0
        assert document["languages"]
        assert document["trust_tier"]

    def test_paging_is_limit_and_offset(self, api: TestClient, reader: str) -> None:
        first = api.get("/v1/documents?limit=1&offset=0", headers=auth(reader)).json()
        assert len(first["documents"]) == 1
        assert first["limit"] == 1

        beyond = api.get("/v1/documents?limit=1&offset=99", headers=auth(reader)).json()
        assert beyond["documents"] == []
        assert beyond["total"] == first["total"]

    def test_a_limit_above_the_cap_is_refused(self, api: TestClient, reader: str) -> None:
        assert api.get("/v1/documents?limit=500", headers=auth(reader)).status_code == 422

    def test_one_document_returns_its_shape_not_its_whole_text(
        self, api: TestClient, reader: str
    ) -> None:
        """A thousand clauses in one response is the context window problem."""
        response = api.get("/v1/documents/testlaw", headers=auth(reader))

        assert response.status_code == 200
        body = response.json()
        assert body["document"]["slug"] == "testlaw"
        assert body["outline"]
        assert len(body["outline"]) < body["document"]["clauses"]

    def test_the_outline_says_what_each_clause_is_and_not_what_it_says(
        self, api: TestClient, reader: str
    ) -> None:
        """An outline carrying text would return whole documents.

        The fixture's top-level clauses do hold text, and a recital holds nothing
        but text, so this is the case that would bite.
        """
        entry = api.get("/v1/documents/testlaw", headers=auth(reader)).json()["outline"][0]

        assert set(entry) == {"key", "clause_type", "label", "heading", "is_normative", "children"}
        assert entry["key"].startswith("testlaw:")
        assert entry["children"] >= 1

    def test_the_outline_counts_what_is_beneath_each_entry(
        self, api: TestClient, reader: str
    ) -> None:
        """So a client knows whether asking for the subtree is worth it."""
        outline = api.get("/v1/documents/testlaw", headers=auth(reader)).json()["outline"]
        entry = outline[0]

        branch = api.get(f"/v1/clauses/{entry['key']}/subtree", headers=auth(reader)).json()
        direct = [
            clause
            for clause in branch[1:]
            if clause["key"].count(":") == entry["key"].count(":") + 1
        ]
        assert entry["children"] == len(direct)

    def test_a_document_whose_top_level_is_all_text_stays_small(
        self, api: TestClient, reader: str
    ) -> None:
        """Recitals are the reason the outline holds no text: each one is text."""
        response = api.get("/v1/documents/testlaw-recitals", headers=auth(reader))

        assert response.status_code == 200
        outline = response.json()["outline"]
        assert outline
        assert all("text" not in entry for entry in outline)

    def test_a_document_nobody_has(self, api: TestClient, reader: str) -> None:
        response = api.get("/v1/documents/nothing-here", headers=auth(reader))

        assert response.status_code == 404
        assert "nothing-here" in response.json()["detail"]

    def test_a_date_before_anything_was_published(self, api: TestClient, reader: str) -> None:
        yesterday = date.today() - timedelta(days=36500)
        response = api.get(f"/v1/documents?as_of={yesterday}", headers=auth(reader))

        assert response.status_code == 200
        assert response.json()["documents"] == []
