"""The logs, read through the API: the questions log, the governance log, the Overview and
how often a clause was cited.

In a database of its own, seeded once: a handful of questions from two developers, one of
them nine days old, so the counts below are this module's and nobody else's.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, update

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.models import User
from dpolens.engine.auth.passwords import set_password
from dpolens.engine.auth.roles import create_role
from dpolens.engine.auth.users import create_user
from dpolens.engine.logs.governance import (
    GOVERNANCE_EXPORTED,
    QUERY_LOG_IDENTITIES_VIEWED,
    Actor,
)
from dpolens.engine.logs.models import GovernanceEntry, QueryLogEntry
from dpolens.engine.logs.queries import Returned, record_query
from dpolens.engine.packs.load import load_pack
from dpolens.engine.packs.selection import select_laws
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
PASSWORD = "correct horse battery staple"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
TESTLAW = Path(__file__).parents[1] / "fixtures" / "packs" / "testlaw"
ADMIN = "admin-logs@example.com"
DPO = "dpo-logs@example.com"
OMAR = "omar-logs@example.com"
SARA = "sara-logs@example.com"
LEAD = "lead-logs@example.com"
PRIVACY_LEAD = "Privacy lead"


def hit(key: str) -> Returned:
    return Returned(
        key=key, lang="en", document_slug="testlaw", version_label="2026.1", trust_tier="community"
    )


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    app_url, owner_url = database_of_its_own("dpolens_logs")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, TESTLAW)
        select_laws(opened, ["testlaw"], actor=ACTOR)
        # No seeded role may see who asked, so somebody is given it on purpose.
        create_role(
            opened,
            name=PRIVACY_LEAD,
            actor=ACTOR,
            permissions=(catalog.QUERIES_READ_ALL, catalog.QUERIES_READ_IDENTITIES),
        )
    ids = {}
    for email, role, name in (
        (ADMIN, catalog.ADMIN, "Yousef Haddad"),
        (DPO, catalog.DPO, "Mariam Al Amiri"),
        (OMAR, catalog.DEVELOPER, "Omar Khalil"),
        (SARA, catalog.DEVELOPER, "Sara Nasser"),
        (LEAD, PRIVACY_LEAD, "Noura Saeed"),
    ):
        with session_from(owner) as opened:
            user = create_user(opened, email=email, display_name=name, actor=ACTOR, roles=(role,))
            opened.flush()
            set_password(opened, email=email, password=PASSWORD, actor=ACTOR)
            ids[email] = user.id

    asked = [
        (
            OMAR,
            "mcp",
            "search",
            "how long can we keep failed sign-ins",
            "ok",
            None,
            [hit("testlaw:art-5:para-1"), hit("testlaw:art-6:para-1")],
        ),
        (
            OMAR,
            "mcp",
            "search",
            "can I log jane@example.com when a webhook fails",
            "ok",
            None,
            [hit("testlaw:art-6:para-1")],
        ),
        (SARA, "mcp", "search", "retention period for cctv footage", "no_match", None, []),
        (
            SARA,
            "dashboard",
            "get_clause",
            "",
            "ok",
            "testlaw:art-5:para-1",
            [hit("testlaw:art-5:para-1")],
        ),
        (SARA, "dashboard", "list_documents", "", "ok", None, []),
    ]
    with session_from(owner) as opened:
        recorded = []
        for email, surface, operation, query, status, target, results in asked:
            recorded.append(
                record_query(
                    opened,
                    user_id=ids[email],
                    pat_id=None,
                    surface=surface,
                    operation=operation,
                    status=status,
                    query=query,
                    target=target,
                    results=results,
                    scope="selected" if operation == "search" else None,
                )
            )
        # One transaction gives every row the same now(); a minute apart, in the order
        # asked, the newest last, so "newest first" has one right answer.
        for minutes_ago, entry_id in enumerate(reversed(recorded)):
            opened.execute(
                update(QueryLogEntry)
                .where(QueryLogEntry.id == entry_id)
                .values(created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago + 1))
            )
        old = record_query(
            opened,
            user_id=ids[SARA],
            pat_id=None,
            surface="mcp",
            operation="search",
            status="ok",
            query="a question from before the week",
            results=[hit("testlaw:art-6:para-1")],
            scope="selected",
        )
        opened.execute(
            update(QueryLogEntry)
            .where(QueryLogEntry.id == old)
            .values(created_at=datetime.now(UTC) - timedelta(days=9))
        )
    yield app_url, owner
    owner.dispose()


@pytest.fixture
def owner(own: tuple[str, Engine]) -> Engine:
    return own[1]


@pytest.fixture(scope="module")
def app_client(own: tuple[str, Engine]) -> Iterator[TestClient]:
    app = create_app(Settings.model_validate({"database_url": own[0]}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def signed_in(client: TestClient, email: str) -> TestClient:
    client.cookies.clear()
    response = client.post(
        "/v1/sessions", json={"email": email, "password": PASSWORD}, headers=SAME_ORIGIN
    )
    assert response.status_code == 201, response.text
    return client


def entries(owner: Engine, action: str) -> list[GovernanceEntry]:
    with session_from(owner) as opened:
        rows = opened.scalars(
            select(GovernanceEntry)
            .where(GovernanceEntry.action == action)
            .order_by(GovernanceEntry.seq)
        ).all()
        opened.expunge_all()
        return list(rows)


def week_ago() -> str:
    return (datetime.now(UTC) - timedelta(days=7)).isoformat()


class TestTheQuestionsLog:
    def test_everyone_s_questions_come_without_names(self, app_client: TestClient) -> None:
        response = signed_in(app_client, DPO).get(
            "/v1/queries", params={"since": week_ago()}, headers=SAME_ORIGIN
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["identities"] is False
        assert body["total"] == 3
        assert all(question["asker"] is None for question in body["questions"])
        assert body["questions"][0]["question"] == "retention period for cctv footage"

    def test_a_question_comes_redacted_with_what_it_returned(self, app_client: TestClient) -> None:
        body = (
            signed_in(app_client, DPO)
            .get("/v1/queries", params={"q": "webhook"}, headers=SAME_ORIGIN)
            .json()
        )

        question = body["questions"][0]
        assert "jane@example.com" not in question["question"]
        assert "[redacted:email]" in question["question"]
        assert question["redaction_count"] == 1
        clause = question["results"][0]["clause"]
        assert clause["key"] == "testlaw:art-6:para-1"
        assert clause["document_title"]
        assert clause["version_label"] == "2026.1"
        assert len(clause["trail"]) == 2

    def test_a_question_says_when_it_goes_only_when_a_retention_is_set(
        self, app_client: TestClient, own: tuple[str, Engine]
    ) -> None:
        kept = (
            signed_in(app_client, DPO)
            .get("/v1/queries", params={"q": "webhook"}, headers=SAME_ORIGIN)
            .json()["questions"][0]
        )
        settings = Settings.model_validate({"database_url": own[0], "query_log_retention_days": 30})
        with TestClient(create_app(settings), base_url="https://testserver") as client:
            going = (
                signed_in(client, DPO)
                .get("/v1/queries", params={"q": "webhook"}, headers=SAME_ORIGIN)
                .json()["questions"][0]
            )

        assert kept["expires_at"] is None
        asked = datetime.fromisoformat(going["created_at"])
        assert datetime.fromisoformat(going["expires_at"]) == asked + timedelta(days=30)

    def test_someone_who_may_read_only_their_own_gets_only_their_own(
        self, app_client: TestClient
    ) -> None:
        body = signed_in(app_client, OMAR).get("/v1/queries", headers=SAME_ORIGIN).json()

        assert body["total"] == 2
        assert "cctv" not in json.dumps(body)

    @pytest.mark.parametrize("email", [DPO, ADMIN])
    def test_names_need_their_own_permission(self, app_client: TestClient, email: str) -> None:
        """Neither seeded role that reads every question may see who asked."""
        response = signed_in(app_client, email).get(
            "/v1/queries", params={"identities": "true"}, headers=SAME_ORIGIN
        )

        assert response.status_code == 403
        assert response.json()["permission"] == catalog.QUERIES_READ_IDENTITIES

    def test_a_look_at_names_is_recorded_with_what_was_seen(
        self, app_client: TestClient, owner: Engine
    ) -> None:
        before = len(entries(owner, QUERY_LOG_IDENTITIES_VIEWED))

        body = (
            signed_in(app_client, LEAD)
            .get(
                "/v1/queries",
                params={"identities": "true", "status": "no_match"},
                headers=SAME_ORIGIN,
            )
            .json()
        )

        assert body["identities"] is True
        assert [question["asker"]["display_name"] for question in body["questions"]] == [
            "Sara Nasser"
        ]
        recorded = entries(owner, QUERY_LOG_IDENTITIES_VIEWED)
        assert len(recorded) == before + 1
        assert recorded[-1].details["entries"] == [body["questions"][0]["id"]]
        assert recorded[-1].details["filters"]["statuses"] == ["no_match"]

    def test_filters_narrow_what_comes_back(self, app_client: TestClient) -> None:
        reader = signed_in(app_client, DPO)

        unanswered = reader.get(
            "/v1/queries", params={"status": "no_match"}, headers=SAME_ORIGIN
        ).json()
        reads = reader.get(
            "/v1/queries",
            params={"operation": "get_clause", "surface": "dashboard"},
            headers=SAME_ORIGIN,
        ).json()
        from_the_law = reader.get(
            "/v1/queries", params={"document": "testlaw", "since": week_ago()}, headers=SAME_ORIGIN
        ).json()

        assert unanswered["total"] == 1
        assert reads["questions"][0]["target"] == "testlaw:art-5:para-1"
        assert from_the_law["total"] == 2

    def test_pages_follow_one_another_without_repeating(self, app_client: TestClient) -> None:
        reader = signed_in(app_client, DPO)

        first = reader.get(
            "/v1/queries", params={"limit": 2, "since": week_ago()}, headers=SAME_ORIGIN
        ).json()
        second = reader.get(
            "/v1/queries",
            params={"limit": 2, "since": week_ago(), "before": first["next"]},
            headers=SAME_ORIGIN,
        ).json()

        ids = [q["id"] for q in first["questions"]] + [q["id"] for q in second["questions"]]
        assert len(ids) == len(set(ids)) == 3
        assert second["next"] is None

    @pytest.mark.parametrize(
        "cursor",
        [
            "not-a-cursor",
            # Well-formed JSON in the right shape, with a number where the id goes.
            base64.urlsafe_b64encode(b'["2026-10-15T09:00:00+00:00", 5]').decode(),
        ],
    )
    def test_a_cursor_that_is_not_one_is_refused(self, app_client: TestClient, cursor: str) -> None:
        response = signed_in(app_client, DPO).get(
            "/v1/queries", params={"before": cursor}, headers=SAME_ORIGIN
        )

        assert response.status_code == 400

    def test_the_export_is_csv_without_names(self, app_client: TestClient) -> None:
        response = signed_in(app_client, DPO).get(
            "/v1/queries/export", params={"since": week_ago()}, headers=SAME_ORIGIN
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(response.text)))
        assert rows[0][:4] == ["time_utc", "surface", "operation", "question"]
        assert "asker" not in rows[0]
        assert len(rows) == 4

    def test_an_export_with_names_is_recorded_with_its_size(
        self, app_client: TestClient, owner: Engine
    ) -> None:
        response = signed_in(app_client, LEAD).get(
            "/v1/queries/export",
            params={"identities": "true", "since": week_ago()},
            headers=SAME_ORIGIN,
        )

        rows = list(csv.reader(io.StringIO(response.text)))
        assert rows[0][-2:] == ["asker", "asker_email"]
        recorded = entries(owner, QUERY_LOG_IDENTITIES_VIEWED)[-1]
        assert recorded.details["exported"] is True
        assert recorded.details["count"] == len(rows) - 1 == 3
        # The file ends where the record was written.
        assert recorded.details["filters"]["until"] is not None


class TestTheGovernanceLog:
    def test_it_needs_governance_read(self, app_client: TestClient) -> None:
        response = signed_in(app_client, OMAR).get("/v1/governance/entries", headers=SAME_ORIGIN)

        assert response.status_code == 403

    def test_entries_come_newest_first_with_names(self, app_client: TestClient) -> None:
        body = (
            signed_in(app_client, DPO)
            .get("/v1/governance/entries", params={"category": "people"}, headers=SAME_ORIGIN)
            .json()
        )

        seqs = [entry["seq"] for entry in body["entries"]]
        assert seqs == sorted(seqs, reverse=True)
        assert all(entry["action"].startswith("user.") for entry in body["entries"])
        created = [entry for entry in body["entries"] if entry["action"] == "user.created"]
        assert {entry["target_user"]["display_name"] for entry in created} >= {
            "Omar Khalil",
            "Sara Nasser",
        }
        assert created[0]["details"]["via"] == "cli"
        assert len(created[0]["entry_hash"]) == 64

    def test_words_find_entries_by_who_they_are_about(self, app_client: TestClient) -> None:
        body = (
            signed_in(app_client, DPO)
            .get("/v1/governance/entries", params={"q": "Sara Nasser"}, headers=SAME_ORIGIN)
            .json()
        )

        assert body["entries"]
        assert all(
            (entry["target_user"] or {}).get("display_name") == "Sara Nasser"
            or (entry["actor"] or {}).get("display_name") == "Sara Nasser"
            for entry in body["entries"]
        )

    def test_the_people_who_acted_can_be_chosen_from(self, app_client: TestClient) -> None:
        signed_in(app_client, DPO)

        people = app_client.get("/v1/governance/actors", headers=SAME_ORIGIN).json()["people"]

        assert "Mariam Al Amiri" in {person["display_name"] for person in people}

    def test_the_chain_is_checked_on_request(self, app_client: TestClient) -> None:
        body = (
            signed_in(app_client, DPO)
            .get("/v1/governance/verification", headers=SAME_ORIGIN)
            .json()
        )

        assert body["ok"] is True
        assert body["anchored_to_genesis"] is True
        assert body["entries"] > 0

    def test_an_export_is_the_three_files_and_is_recorded(
        self, app_client: TestClient, owner: Engine
    ) -> None:
        before = len(entries(owner, GOVERNANCE_EXPORTED))

        response = signed_in(app_client, DPO).post("/v1/governance/exports", headers=SAME_ORIGIN)

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            assert sorted(bundle.namelist()) == ["actors.json", "entries.jsonl", "manifest.json"]
            manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["anchored_to_genesis"] is True
        assert len(entries(owner, GOVERNANCE_EXPORTED)) == before + 1


class TestTheOverview:
    def test_it_needs_every_question(self, app_client: TestClient) -> None:
        response = signed_in(app_client, OMAR).get("/v1/overview", headers=SAME_ORIGIN)

        assert response.status_code == 403

    def test_the_week_in_numbers_and_no_names(self, app_client: TestClient) -> None:
        response = signed_in(app_client, DPO).get(
            "/v1/overview", params={"days": 7, "tz": "Asia/Dubai"}, headers=SAME_ORIGIN
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["questions"], body["answered"], body["found_nothing"]) == (3, 2, 1)
        assert body["previous_questions"] == 1
        assert len(body["by_day"]) == 7
        assert (
            sum(day["assistants"] + day["dashboard"] + day["other"] for day in body["by_day"]) == 3
        )
        # Omar's first search cited it; Sara reading it in the dashboard did not.
        top = body["most_cited"][0]
        assert (top["clause"]["key"], top["count"]) == ("testlaw:art-5:para-1", 1)
        assert body["sources"] == [
            {"pack_slug": "testlaw", "title": body["sources"][0]["title"], "count": 2}
        ]
        assert [question["question"] for question in body["unanswered"]] == [
            "retention period for cctv footage"
        ]
        assert [law["slug"] for law in body["laws"]] == ["testlaw"]
        assert "Sara" not in json.dumps(body)

    def test_a_time_zone_it_does_not_know_is_refused(self, app_client: TestClient) -> None:
        response = signed_in(app_client, DPO).get(
            "/v1/overview", params={"tz": "Mars/Olympus_Mons"}, headers=SAME_ORIGIN
        )

        assert response.status_code == 400

    def test_a_clause_s_citations_day_by_day(self, app_client: TestClient) -> None:
        body = (
            signed_in(app_client, DPO)
            .get(
                "/v1/clauses/testlaw:art-5:para-1/activity", params={"days": 7}, headers=SAME_ORIGIN
            )
            .json()
        )

        assert body["total"] == 1
        assert len(body["by_day"]) == 7
        assert body["by_day"][-1]["count"] == 1


def test_the_seeded_people_exist(owner: Engine) -> None:
    """A guard for the module's fixture, so a failure above is about the logs."""
    with session_from(owner) as opened:
        names = set(opened.scalars(select(User.display_name)))
    assert {
        "Omar Khalil",
        "Sara Nasser",
        "Mariam Al Amiri",
        "Yousef Haddad",
        "Noura Saeed",
    } <= names
