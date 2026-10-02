"""The query log, through the API that writes it.

Two promises are under test. What a developer typed is stored redacted, and it is
stored at all only for as long as the retention allows. The third thing worth
proving is that the question never reaches telemetry, which has no redaction, no
permissions and no expiry.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user
from dpolens.engine.embedding import DEFAULT_MODEL, get_model
from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.index import build_index
from dpolens.engine.logs.governance import Actor, read_entries
from dpolens.engine.logs.models import QueryLogEntry, QueryLogResult
from dpolens.engine.logs.queries import QUERY_LOG_PURGED, count_entries, purge_expired
from dpolens.engine.packs.load import load_pack
from dpolens.engine.session import session_from
from dpolens.settings import Settings
from dpolens.telemetry import configure

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
TESTLAW = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"


@pytest.fixture(scope="module")
def corpus(committed_owner_url: str) -> Iterator[Engine]:
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
    app = create_app(
        Settings.model_validate(
            {
                "database_url": committed_database_url,
                "redaction_patterns": {"case_number": r"\bCASE-\d{4}\b"},
            }
        )
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def reader(corpus: Engine) -> str:
    email = f"log-reader-{uuid.uuid4().hex[:8]}@example.com"
    with session_from(corpus) as opened:
        create_user(
            opened, email=email, display_name="Reader", actor=ACTOR, roles=(catalog.DEVELOPER,)
        )
        opened.flush()
        _, token = mint(
            opened, email=email, name="log", permissions=(catalog.DOCUMENTS_READ,), actor=ACTOR
        )
    return token


@pytest.fixture
def opened(corpus: Engine) -> Iterator[Session]:
    with session_from(corpus) as session:
        yield session


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def latest(session: Session) -> QueryLogEntry:
    session.expire_all()
    return session.scalars(
        select(QueryLogEntry).order_by(QueryLogEntry.created_at.desc()).limit(1)
    ).one()


class TestWhatIsRecorded:
    def test_a_search_is_recorded_with_what_it_returned(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        response = api.post(
            "/v1/search", json={"query": "erasure of personal data"}, headers=auth(reader)
        )
        assert response.status_code == 200

        entry = latest(opened)
        assert entry.operation == "search"
        assert entry.surface == "api"
        assert entry.status == "ok"
        assert entry.query_redacted == "erasure of personal data"
        results = opened.scalars(
            select(QueryLogResult)
            .where(QueryLogResult.query_log_entry_id == entry.id)
            .order_by(QueryLogResult.rank)
        ).all()
        assert results
        assert results[0].rank == 1
        assert results[0].canonical_key.startswith("testlaw:")
        assert results[0].document_version_id

    def test_a_question_nothing_answers_is_still_recorded(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        """The most useful row in the table: a real phrasing the corpus missed."""
        api.post(
            "/v1/search",
            json={"query": "zzz unrelated astrophysics", "as_of": "1990-01-01"},
            headers=auth(reader),
        )

        entry = latest(opened)
        assert entry.status == "no_match"
        assert entry.query_redacted == "zzz unrelated astrophysics"

    def test_reading_a_clause_records_the_key_and_no_question(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        """The key is not something somebody typed, so it is kept apart from it."""
        found = api.post("/v1/search", json={"query": "data"}, headers=auth(reader)).json()
        key = found["results"][0]["clause"]["key"]

        api.get(f"/v1/clauses/{key}", headers=auth(reader))

        entry = latest(opened)
        assert entry.operation == "get_clause"
        assert entry.target == key
        assert entry.query_redacted == ""

    def test_a_key_that_does_not_exist_is_recorded_as_a_miss(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        """A 404 rolls the request back, so the row is written in its own transaction."""
        api.get("/v1/clauses/testlaw:art-404", headers=auth(reader))

        entry = latest(opened)
        assert entry.operation == "get_clause"
        assert entry.status == "no_match"
        assert entry.target == "testlaw:art-404"

    def test_listing_documents_is_recorded(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        api.get("/v1/documents", headers=auth(reader))

        entry = latest(opened)
        assert entry.operation == "list_documents"
        assert entry.status == "ok"

    def test_the_row_names_the_developer_and_their_token(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        api.post("/v1/search", json={"query": "data"}, headers=auth(reader))

        entry = latest(opened)
        assert entry.actor_user_id
        assert entry.actor_pat_id

    def test_an_expiry_is_set_from_the_retention(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        api.post("/v1/search", json={"query": "data"}, headers=auth(reader))

        entry = latest(opened)
        expected = datetime.now(UTC) + timedelta(days=365)
        assert abs((entry.expires_at - expected).total_seconds()) < 60


class TestRedaction:
    def test_an_address_in_a_question_is_not_stored(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        api.post(
            "/v1/search",
            json={"query": "can we email hamad@example.com about erasure"},
            headers=auth(reader),
        )

        entry = latest(opened)
        assert "hamad@example.com" not in entry.query_redacted
        assert "[redacted:email]" in entry.query_redacted
        assert entry.redaction_count == 1
        assert entry.redaction_types == ["email"]

    def test_the_raw_question_is_nowhere_in_the_row(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        """There is no column for it, which is the point of having no column."""
        api.post(
            "/v1/search", json={"query": "card 4242 4242 4242 4242 retention"}, headers=auth(reader)
        )

        entry = latest(opened)
        stored = (
            opened.execute(text("SELECT * FROM query_log_entries WHERE id = :id"), {"id": entry.id})
            .mappings()
            .one()
        )
        assert "4242" not in json.dumps(dict(stored), default=str)

    def test_an_operators_own_pattern_is_applied_and_named(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        """Configuration exists for the identifier format we did not think of."""
        api.post(
            "/v1/search", json={"query": "what about CASE-1234 retention"}, headers=auth(reader)
        )

        entry = latest(opened)
        assert "CASE-1234" not in entry.query_redacted
        assert "case_number" in entry.redaction_types


class TestTelemetryNeverSeesTheQuestion:
    def test_the_question_does_not_reach_telemetry(
        self, api: TestClient, reader: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Telemetry has no redaction, no permissions and no expiry, so it gets
        identifiers and counts and never the words."""
        configure()
        secret = "hamad@example.com asked about erasure of everything"

        api.post("/v1/search", json={"query": secret}, headers=auth(reader))

        printed = capsys.readouterr().out
        assert "corpus.asked" in printed
        assert secret not in printed
        assert "hamad@example.com" not in printed
        assert "erasure" not in printed


class TestRetention:
    def test_an_expired_entry_is_deleted_and_a_fresh_one_is_kept(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        api.post("/v1/search", json={"query": "kept"}, headers=auth(reader))
        fresh = latest(opened).id

        api.post("/v1/search", json={"query": "expired"}, headers=auth(reader))
        stale = latest(opened)
        stale_id = stale.id
        stale.expires_at = datetime.now(UTC) - timedelta(days=1)
        opened.commit()

        deleted = purge_expired(opened, actor=ACTOR)
        opened.commit()
        # A bulk delete does not tell the session what it removed, so the cached
        # objects have to be forgotten before asking again.
        opened.expunge_all()

        assert deleted >= 1
        assert opened.get(QueryLogEntry, stale_id) is None
        assert opened.get(QueryLogEntry, fresh) is not None

    def test_the_purge_is_recorded_once_and_not_when_nothing_expired(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        api.post("/v1/search", json={"query": "to expire"}, headers=auth(reader))
        entry = latest(opened)
        entry.expires_at = datetime.now(UTC) - timedelta(days=1)
        opened.commit()
        before = len(read_entries(opened))

        purge_expired(opened, actor=ACTOR)
        opened.commit()
        after_one = read_entries(opened)[before:]
        assert [row.action for row in after_one] == [QUERY_LOG_PURGED]
        assert after_one[0].details_text.startswith('{"deleted":')

        # A daily run with nothing to do writes nothing, or the log fills with
        # entries saying nothing happened.
        before = len(read_entries(opened))
        assert purge_expired(opened, actor=ACTOR) == 0
        opened.commit()
        assert len(read_entries(opened)) == before

    def test_deleting_an_entry_takes_its_results_with_it(
        self, api: TestClient, reader: str, opened: Session
    ) -> None:
        api.post("/v1/search", json={"query": "erasure"}, headers=auth(reader))
        entry = latest(opened)
        results = opened.scalars(
            select(QueryLogResult.id).where(QueryLogResult.query_log_entry_id == entry.id)
        ).all()
        assert results

        entry.expires_at = datetime.now(UTC) - timedelta(days=1)
        opened.commit()
        purge_expired(opened, actor=ACTOR)
        opened.commit()
        opened.expunge_all()

        assert opened.get(QueryLogResult, results[0]) is None

    def test_counting_what_is_kept(self, api: TestClient, reader: str, opened: Session) -> None:
        before = count_entries(opened)

        api.post("/v1/search", json={"query": "one more"}, headers=auth(reader))

        opened.expire_all()
        assert count_entries(opened) == before + 1
