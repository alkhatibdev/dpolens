"""Tokens from the dashboard: making one, listing one's own and everyone's, revoking.

In a database of its own: tokens are never deleted, and the lists count them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.passwords import set_password
from dpolens.engine.auth.users import create_user, revoke_role
from dpolens.engine.logs.governance import Actor
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
PASSWORD = "correct horse battery staple"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
ADMIN = "admin-tokens@example.com"


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    app_url, owner_url = database_of_its_own("dpolens_tokens_api")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
    add(owner, ADMIN, (catalog.ADMIN,))
    yield app_url, owner
    owner.dispose()


def add(owner: Engine, email: str, roles: tuple[str, ...]) -> None:
    with session_from(owner) as opened:
        create_user(opened, email=email, display_name=email.split("@")[0], actor=ACTOR, roles=roles)
        opened.flush()
        set_password(opened, email=email, password=PASSWORD, actor=ACTOR)


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


@pytest.fixture
def developer(owner: Engine, unique: str) -> str:
    email = f"dev-{unique}@example.com"
    add(owner, email, (catalog.DEVELOPER,))
    return email


def make(
    client: TestClient, name: str, permissions: list[str], **extra: object
) -> dict[str, object]:
    response = client.post(
        "/v1/tokens",
        json={"name": name, "permissions": permissions, **extra},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


class TestMaking:
    def test_a_token_is_shown_once_and_works(self, app_client: TestClient, developer: str) -> None:
        made = make(signed_in(app_client, developer), "laptop", [catalog.DOCUMENTS_READ])

        assert str(made["secret"]).startswith("dpol_")
        assert made["status"] == "active"
        assert made["permissions"] == [catalog.DOCUMENTS_READ]
        app_client.cookies.clear()
        with_it = app_client.get(
            "/v1/permissions", headers={"Authorization": f"Bearer {made['secret']}"}
        )
        assert with_it.status_code == 200
        listed = signed_in(app_client, developer).get("/v1/tokens", headers=SAME_ORIGIN).json()
        assert all("secret" not in token for token in listed["tokens"])

    def test_a_token_cannot_make_a_token(self, app_client: TestClient, developer: str) -> None:
        made = make(signed_in(app_client, developer), "laptop", [catalog.DOCUMENTS_READ])
        app_client.cookies.clear()

        response = app_client.post(
            "/v1/tokens",
            json={"name": "copy", "permissions": [catalog.DOCUMENTS_READ]},
            headers={"Authorization": f"Bearer {made['secret']}"},
        )

        assert response.status_code == 403
        assert response.json()["type"] == "/problems/session-required"

    def test_a_token_cannot_be_given_what_its_owner_lacks(
        self, app_client: TestClient, developer: str
    ) -> None:
        response = signed_in(app_client, developer).post(
            "/v1/tokens",
            json={"name": "greedy", "permissions": [catalog.QUERIES_READ_ALL]},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 403
        assert response.json()["permission"] == catalog.QUERIES_READ_ALL

    def test_an_expiry_in_the_past_is_refused(self, app_client: TestClient, developer: str) -> None:
        response = signed_in(app_client, developer).post(
            "/v1/tokens",
            json={
                "name": "late",
                "permissions": [catalog.DOCUMENTS_READ],
                "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            },
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 400

    def test_an_expiry_is_kept(self, app_client: TestClient, developer: str) -> None:
        when = datetime.now(UTC) + timedelta(days=90)

        made = make(
            signed_in(app_client, developer),
            "ninety",
            [catalog.DOCUMENTS_READ],
            expires_at=when.isoformat(),
        )

        assert datetime.fromisoformat(str(made["expires_at"])) == when


class TestListing:
    def test_a_person_sees_their_own_tokens(
        self, app_client: TestClient, developer: str, owner: Engine, unique: str
    ) -> None:
        other = f"other-{unique}@example.com"
        add(owner, other, (catalog.DEVELOPER,))
        make(signed_in(app_client, other), "theirs", [catalog.DOCUMENTS_READ])
        make(signed_in(app_client, developer), "mine", [catalog.DOCUMENTS_READ])

        listed = app_client.get("/v1/tokens", headers=SAME_ORIGIN).json()["tokens"]

        assert [token["name"] for token in listed] == ["mine"]

    def test_everyone_s_tokens_need_users_manage(
        self, app_client: TestClient, developer: str
    ) -> None:
        response = signed_in(app_client, developer).get(
            "/v1/tokens", params={"everyone": "true"}, headers=SAME_ORIGIN
        )

        assert response.status_code == 403
        assert response.json()["permission"] == catalog.USERS_MANAGE

    def test_an_administrator_sees_everyone_s(self, app_client: TestClient, developer: str) -> None:
        make(signed_in(app_client, developer), "seen", [catalog.DOCUMENTS_READ])

        listed = signed_in(app_client, ADMIN).get(
            "/v1/tokens", params={"everyone": "true"}, headers=SAME_ORIGIN
        )

        owners = {token["owner"]["display_name"] for token in listed.json()["tokens"]}
        assert developer.split("@")[0] in owners

    def test_a_token_narrows_when_its_owner_loses_a_permission(
        self, app_client: TestClient, developer: str, owner: Engine
    ) -> None:
        make(
            signed_in(app_client, developer),
            "scripts",
            [catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN],
        )
        with session_from(owner) as opened:
            revoke_role(opened, email=developer, role_name=catalog.DEVELOPER, actor=ACTOR)

        listed = signed_in(app_client, ADMIN).get(
            "/v1/tokens", params={"everyone": "true"}, headers=SAME_ORIGIN
        )

        token = next(
            token
            for token in listed.json()["tokens"]
            if token["name"] == "scripts"
            and token["owner"]["display_name"] == developer.split("@")[0]
        )
        assert token["permissions"] == [catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN]
        assert token["effective_permissions"] == []


class TestRevoking:
    def test_a_person_revokes_their_own(self, app_client: TestClient, developer: str) -> None:
        made = make(signed_in(app_client, developer), "laptop", [catalog.DOCUMENTS_READ])

        response = app_client.delete(f"/v1/tokens/{made['id']}", headers=SAME_ORIGIN)

        assert response.status_code == 204
        listed = app_client.get("/v1/tokens", headers=SAME_ORIGIN).json()["tokens"]
        assert next(token for token in listed if token["id"] == made["id"])["status"] == "revoked"

    def test_someone_else_s_token_is_not_found_without_users_manage(
        self, app_client: TestClient, developer: str, owner: Engine, unique: str
    ) -> None:
        made = make(signed_in(app_client, developer), "laptop", [catalog.DOCUMENTS_READ])
        stranger = f"stranger-{unique}@example.com"
        add(owner, stranger, (catalog.DEVELOPER,))

        response = signed_in(app_client, stranger).delete(
            f"/v1/tokens/{made['id']}", headers=SAME_ORIGIN
        )

        assert response.status_code == 404

    def test_an_administrator_revokes_anyone_s(
        self, app_client: TestClient, developer: str
    ) -> None:
        made = make(signed_in(app_client, developer), "leaked", [catalog.DOCUMENTS_READ])

        response = signed_in(app_client, ADMIN).delete(
            f"/v1/tokens/{made['id']}", headers=SAME_ORIGIN
        )

        assert response.status_code == 204
        app_client.cookies.clear()
        refused = app_client.get(
            "/v1/permissions", headers={"Authorization": f"Bearer {made['secret']}"}
        )
        assert refused.status_code == 401
        assert refused.json()["reason"] == "revoked"


def test_the_instance_says_where_assistants_connect(app_client: TestClient, developer: str) -> None:
    response = signed_in(app_client, developer).get("/v1/instance", headers=SAME_ORIGIN)

    assert response.status_code == 200
    assert response.json()["mcp_url"] == "http://localhost:8765/mcp"
    assert response.json()["version"]
