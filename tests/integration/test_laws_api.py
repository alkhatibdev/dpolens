"""Selected laws and the instance's settings, through the API.

In a database of its own, with the two fixture laws loaded. Only one test changes the
selection, because the first thing it checks is a state no instance returns to: nobody
has chosen yet. The others leave the selection as they found it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.passwords import set_password
from dpolens.engine.auth.users import create_user
from dpolens.engine.instance import Instance
from dpolens.engine.logs.governance import LAWS_SELECTED, Actor
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.packs.load import load_pack
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
PASSWORD = "correct horse battery staple"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
PACKS = Path(__file__).parents[1] / "fixtures" / "packs"
ADMIN = "admin-laws@example.com"
DPO = "dpo-laws@example.com"
DEVELOPER = "dev-laws@example.com"


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    app_url, owner_url = database_of_its_own("dpolens_laws")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, PACKS / "testlaw")
        load_pack(opened, PACKS / "bilingual")
    for email, role, name in (
        (ADMIN, catalog.ADMIN, "Yousef Haddad"),
        (DPO, catalog.DPO, "Mariam Al Amiri"),
        (DEVELOPER, catalog.DEVELOPER, "Omar Khalil"),
    ):
        with session_from(owner) as opened:
            create_user(opened, email=email, display_name=name, actor=ACTOR, roles=(role,))
            opened.flush()
            set_password(opened, email=email, password=PASSWORD, actor=ACTOR)
    yield app_url, owner
    owner.dispose()


@pytest.fixture(scope="module")
def app_client(own: tuple[str, Engine]) -> Iterator[TestClient]:
    settings = Settings.model_validate(
        {"database_url": own[0], "redaction_patterns": {"staff_id": r"EMP-\d{6}"}}
    )
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        yield client


def signed_in(client: TestClient, email: str) -> TestClient:
    client.cookies.clear()
    response = client.post(
        "/v1/sessions", json={"email": email, "password": PASSWORD}, headers=SAME_ORIGIN
    )
    assert response.status_code == 201, response.text
    return client


def selection_entries(owner: Engine) -> list[GovernanceEntry]:
    with session_from(owner) as opened:
        rows = opened.scalars(
            select(GovernanceEntry)
            .where(GovernanceEntry.action == LAWS_SELECTED)
            .order_by(GovernanceEntry.seq)
        ).all()
        opened.expunge_all()
        return list(rows)


class TestSelectedLaws:
    def test_from_nobody_choosing_to_a_choice(
        self, app_client: TestClient, own: tuple[str, Engine]
    ) -> None:
        client = signed_in(app_client, ADMIN)

        fresh = client.get("/v1/laws", headers=SAME_ORIGIN)
        assert fresh.status_code == 200, fresh.text
        assert fresh.json()["selected"] is None
        assert fresh.json()["changed"] is None
        # Nothing is searched until somebody chooses, and nothing has arrived since.
        assert [law["searched"] for law in fresh.json()["laws"]] == [False, False]
        assert [law["new"] for law in fresh.json()["laws"]] == [False, False]

        chosen = client.put("/v1/laws/selection", json={"laws": ["bilingual"]}, headers=SAME_ORIGIN)
        assert chosen.status_code == 200, chosen.text
        body = chosen.json()
        assert body["selected"] == ["bilingual"]
        assert {law["slug"]: law["searched"] for law in body["laws"]} == {
            "bilingual": True,
            "testlaw": False,
        }
        assert body["changed"]["by"] == "Yousef Haddad"
        assert body["changed"]["via"] == "dashboard"

        written = selection_entries(own[1])
        assert [entry.action for entry in written] == [LAWS_SELECTED]
        assert written[0].details["after"] == ["bilingual"]
        assert written[0].details["via"] == "dashboard"

    def test_there_is_no_going_back_to_every_law(self, app_client: TestClient) -> None:
        response = signed_in(app_client, ADMIN).delete("/v1/laws/selection", headers=SAME_ORIGIN)

        assert response.status_code == 405

    def test_each_law_says_what_it_holds(self, app_client: TestClient) -> None:
        laws = signed_in(app_client, DPO).get("/v1/laws", headers=SAME_ORIGIN).json()["laws"]

        bilingual, testlaw = laws
        assert bilingual["slug"] == "bilingual"
        assert bilingual["authoritative_language"] == "ar"
        assert bilingual["languages"] == ["ar", "en"]
        assert (bilingual["articles"], bilingual["recitals"]) == (3, 0)
        assert bilingual["document"] == "bilingual"
        assert testlaw["name"] == "Test Data Protection Law"
        assert testlaw["jurisdiction"] == "Example Republic"
        assert (testlaw["version"], testlaw["effective_date"]) == ("2026.1", "2026-01-01")
        assert testlaw["trust_tier"] == "community"
        assert (testlaw["articles"], testlaw["recitals"]) == (2, 1)
        # The recitals are a document of their own; the page links to the articles.
        assert testlaw["document"] == "testlaw"

    def test_a_law_that_is_not_loaded_is_refused_with_the_ones_that_are(
        self, app_client: TestClient, own: tuple[str, Engine]
    ) -> None:
        before = len(selection_entries(own[1]))

        response = signed_in(app_client, ADMIN).put(
            "/v1/laws/selection", json={"laws": ["bilingual", "atlantis"]}, headers=SAME_ORIGIN
        )

        assert response.status_code == 422
        assert response.json()["laws"] == ["bilingual", "testlaw"]
        assert len(selection_entries(own[1])) == before

    def test_a_selection_names_at_least_one_law(self, app_client: TestClient) -> None:
        response = signed_in(app_client, ADMIN).put(
            "/v1/laws/selection", json={"laws": []}, headers=SAME_ORIGIN
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("method", "path"),
        [("GET", "/v1/laws"), ("PUT", "/v1/laws/selection")],
    )
    def test_choosing_needs_the_permission_to_change_settings(
        self, app_client: TestClient, method: str, path: str
    ) -> None:
        client = signed_in(app_client, DEVELOPER)

        response = client.request(
            method,
            path,
            json={"laws": ["testlaw"]} if method == "PUT" else None,
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 403


class TestSettings:
    def test_says_how_the_instance_is_set_up(
        self, app_client: TestClient, own: tuple[str, Engine]
    ) -> None:
        response = signed_in(app_client, DPO).get("/v1/settings", headers=SAME_ORIGIN)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["questions_log"] == {
            "retention_days": 365,
            "redacted": ["card", "iban", "emirates_id", "email", "phone"],
            "added_patterns": ["staff_id"],
        }
        assert body["sign_in"] == {
            "idle_minutes": 30,
            "lifetime_hours": 8,
            "wrong_passwords": 5,
            "wrong_password_window_minutes": 15,
        }
        assert body["assistants"] == {
            "mcp_url": "http://localhost:8765/mcp",
            "requests_per_minute": 60,
        }
        assert body["ai_provider"] is None
        with session_from(own[1]) as opened:
            row = opened.scalars(select(Instance)).one()
            assert body["instance"]["id"] == str(row.id)

    def test_reading_them_needs_the_permission_to_change_them(self, app_client: TestClient) -> None:
        response = signed_in(app_client, DEVELOPER).get("/v1/settings", headers=SAME_ORIGIN)

        assert response.status_code == 403
