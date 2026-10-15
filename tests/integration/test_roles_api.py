"""Roles from the dashboard: the catalog, reading roles, editing them against a revision,
and deleting one nobody holds.

In a database of its own whose only administrator is the one signed in, so the
lockout guard has one person to protect.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select

from dpolens.api.app import create_app
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.models import Role
from dpolens.engine.auth.passwords import set_password
from dpolens.engine.auth.roles import grant_permission
from dpolens.engine.auth.users import create_user
from dpolens.engine.logs.governance import (
    ROLE_DESCRIBED,
    ROLE_PERMISSIONS_CHANGED,
    ROLE_RENAMED,
    Actor,
)
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
PASSWORD = "correct horse battery staple"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
ADMIN = "admin-roles@example.com"
DEVELOPER = "developer-roles@example.com"


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    app_url, owner_url = database_of_its_own("dpolens_roles")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
    for email, role, name in (
        (ADMIN, catalog.ADMIN, "Yousef Haddad"),
        (DEVELOPER, catalog.DEVELOPER, "Omar Khalil"),
    ):
        with session_from(owner) as opened:
            create_user(opened, email=email, display_name=name, actor=ACTOR, roles=(role,))
            opened.flush()
            set_password(opened, email=email, password=PASSWORD, actor=ACTOR)
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


@pytest.fixture
def admin(app_client: TestClient) -> TestClient:
    return signed_in(app_client, ADMIN)


def entries(owner: Engine, action: str, target_id: str) -> list[GovernanceEntry]:
    with session_from(owner) as opened:
        rows = opened.scalars(
            select(GovernanceEntry)
            .where(GovernanceEntry.action == action, GovernanceEntry.target_id == target_id)
            .order_by(GovernanceEntry.seq)
        ).all()
        opened.expunge_all()
        return list(rows)


def made(admin: TestClient, name: str, permissions: list[str]) -> dict[str, object]:
    response = admin.post(
        "/v1/roles",
        json={"name": name, "description": "For the test", "permissions": permissions},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 201, response.text
    assert response.headers["ETag"] == '"1"'
    body: dict[str, object] = response.json()
    return body


class TestReading:
    def test_the_catalog_is_open_to_anyone_signed_in(self, app_client: TestClient) -> None:
        response = signed_in(app_client, DEVELOPER).get("/v1/permissions", headers=SAME_ORIGIN)

        assert response.status_code == 200
        keys = [entry["key"] for entry in response.json()["permissions"]]
        assert keys == list(catalog.PERMISSIONS)
        assert all(entry["description"] for entry in response.json()["permissions"])

    def test_roles_need_one_of_two_permissions(self, app_client: TestClient) -> None:
        response = signed_in(app_client, DEVELOPER).get("/v1/roles", headers=SAME_ORIGIN)

        assert response.status_code == 403
        assert response.json()["permissions"] == [catalog.ROLES_MANAGE, catalog.USERS_MANAGE]

    def test_each_role_comes_with_its_holders(self, admin: TestClient) -> None:
        response = admin.get("/v1/roles", headers=SAME_ORIGIN)

        assert response.status_code == 200
        roles = {role["name"]: role for role in response.json()["roles"]}
        assert {catalog.ADMIN, catalog.DPO, catalog.DEVELOPER} <= set(roles)
        assert roles[catalog.ADMIN]["permissions"] == sorted(catalog.SEEDED_ROLES[catalog.ADMIN])
        assert roles[catalog.ADMIN]["is_seeded"] is True
        assert [holder["display_name"] for holder in roles[catalog.DEVELOPER]["holders"]] == [
            "Omar Khalil"
        ]
        assert roles[catalog.DEVELOPER]["updated_by"] is None

    def test_one_role_carries_its_revision_as_an_etag(self, admin: TestClient, unique: str) -> None:
        role = made(admin, f"Reader {unique}", [catalog.DOCUMENTS_READ])

        response = admin.get(f"/v1/roles/{role['id']}", headers=SAME_ORIGIN)

        assert response.status_code == 200
        assert response.headers["ETag"] == '"1"'
        assert response.json()["revision"] == 1
        assert response.json()["updated_by"] == "Yousef Haddad"


class TestCreating:
    def test_a_name_already_taken_is_refused(self, admin: TestClient) -> None:
        response = admin.post("/v1/roles", json={"name": catalog.DPO}, headers=SAME_ORIGIN)

        assert response.status_code == 409
        assert response.json()["type"] == "/problems/already-exists"

    def test_a_permission_outside_the_catalog_is_refused(
        self, admin: TestClient, unique: str
    ) -> None:
        response = admin.post(
            "/v1/roles",
            json={"name": f"Odd {unique}", "permissions": ["documents.delete"]},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 400
        assert "documents.delete" in response.json()["detail"]

    def test_creating_needs_roles_manage(self, app_client: TestClient, unique: str) -> None:
        response = signed_in(app_client, DEVELOPER).post(
            "/v1/roles", json={"name": f"Mine {unique}"}, headers=SAME_ORIGIN
        )

        assert response.status_code == 403
        assert response.json()["permission"] == catalog.ROLES_MANAGE


class TestEditing:
    def test_a_save_against_the_current_revision_is_made(
        self, admin: TestClient, owner: Engine, unique: str
    ) -> None:
        role = made(admin, f"Support {unique}", [catalog.DOCUMENTS_READ])

        response = admin.patch(
            f"/v1/roles/{role['id']}",
            json={"permissions": [catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN]},
            headers={**SAME_ORIGIN, "If-Match": '"1"'},
        )

        assert response.status_code == 200, response.text
        assert response.headers["ETag"] == '"2"'
        assert response.json()["permissions"] == [catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN]
        changed = entries(owner, ROLE_PERMISSIONS_CHANGED, f"Support {unique}")
        assert changed[-1].details["granted"] == [catalog.QUERIES_READ_OWN]
        assert changed[-1].details["revoked"] == []
        assert changed[-1].details["via"] == "dashboard"

    def test_a_save_against_an_older_revision_is_refused_and_says_who(
        self, admin: TestClient, owner: Engine, unique: str
    ) -> None:
        name = f"Contested {unique}"
        role = made(admin, name, [catalog.DOCUMENTS_READ])
        with session_from(owner) as opened:
            grant_permission(
                opened, role_name=name, permission=catalog.QUERIES_READ_OWN, actor=ACTOR
            )

        response = admin.patch(
            f"/v1/roles/{role['id']}",
            json={"permissions": [catalog.DOCUMENTS_READ, catalog.TOKENS_CREATE]},
            headers={**SAME_ORIGIN, "If-Match": '"1"'},
        )

        assert response.status_code == 412
        body = response.json()
        assert body["type"] == "/problems/edit-conflict"
        assert body["revision"] == 2
        assert body["updated_by"] is None
        after = admin.get(f"/v1/roles/{role['id']}", headers=SAME_ORIGIN).json()
        assert after["permissions"] == [catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN]

    def test_a_save_without_a_revision_wins(self, admin: TestClient, unique: str) -> None:
        role = made(admin, f"Loose {unique}", [catalog.DOCUMENTS_READ])

        response = admin.patch(
            f"/v1/roles/{role['id']}",
            json={"permissions": [catalog.TOKENS_CREATE]},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 200
        assert response.json()["permissions"] == [catalog.TOKENS_CREATE]

    def test_a_revision_that_is_not_one_is_refused(self, admin: TestClient, unique: str) -> None:
        role = made(admin, f"Garbled {unique}", [])

        response = admin.patch(
            f"/v1/roles/{role['id']}",
            json={"description": "x"},
            headers={**SAME_ORIGIN, "If-Match": "yesterday"},
        )

        assert response.status_code == 400

    def test_a_rename_keeps_both_names_in_the_log(
        self, admin: TestClient, owner: Engine, unique: str
    ) -> None:
        role = made(admin, f"Before {unique}", [])

        response = admin.patch(
            f"/v1/roles/{role['id']}",
            json={"name": f"After {unique}", "description": "Renamed"},
            headers={**SAME_ORIGIN, "If-Match": '"1"'},
        )

        assert response.status_code == 200
        renamed = entries(owner, ROLE_RENAMED, f"After {unique}")
        assert renamed[-1].details["before"]["name"] == f"Before {unique}"
        assert renamed[-1].details["after"] == {"name": f"After {unique}", "description": "Renamed"}

    def test_a_new_description_alone_is_its_own_entry(
        self, admin: TestClient, owner: Engine, unique: str
    ) -> None:
        name = f"Described {unique}"
        role = made(admin, name, [])

        admin.patch(
            f"/v1/roles/{role['id']}", json={"description": "Now it says"}, headers=SAME_ORIGIN
        )

        assert entries(owner, ROLE_DESCRIBED, name)[-1].details["after"]["description"] == (
            "Now it says"
        )

    def test_a_rename_to_a_name_already_taken_is_refused(
        self, admin: TestClient, unique: str
    ) -> None:
        role = made(admin, f"Twin {unique}", [])

        response = admin.patch(
            f"/v1/roles/{role['id']}", json={"name": catalog.DPO}, headers=SAME_ORIGIN
        )

        assert response.status_code == 409

    def test_the_last_way_to_manage_roles_cannot_be_taken(
        self, admin: TestClient, owner: Engine
    ) -> None:
        with session_from(owner) as opened:
            admin_role = opened.scalars(select(Role).where(Role.name == catalog.ADMIN)).one()
            keys = sorted(admin_role.permission_keys() - {catalog.ROLES_MANAGE})
            role_id = str(admin_role.id)

        response = admin.patch(
            f"/v1/roles/{role_id}", json={"permissions": keys}, headers=SAME_ORIGIN
        )

        assert response.status_code == 409
        assert response.json()["type"] == "/problems/lockout-refused"

    def test_a_change_from_the_command_line_raises_the_revision_too(
        self, admin: TestClient, owner: Engine, unique: str
    ) -> None:
        name = f"Shell {unique}"
        role = made(admin, name, [])
        with session_from(owner) as opened:
            grant_permission(opened, role_name=name, permission=catalog.DOCUMENTS_READ, actor=ACTOR)

        after = admin.get(f"/v1/roles/{role['id']}", headers=SAME_ORIGIN)

        assert after.headers["ETag"] == '"2"'
        assert after.json()["updated_by"] is None


class TestDeleting:
    def test_a_role_somebody_holds_is_refused_with_their_names(
        self, admin: TestClient, owner: Engine
    ) -> None:
        with session_from(owner) as opened:
            role_id = str(
                opened.scalars(select(Role.id).where(Role.name == catalog.DEVELOPER)).one()
            )

        response = admin.delete(f"/v1/roles/{role_id}", headers=SAME_ORIGIN)

        assert response.status_code == 409
        assert response.json()["type"] == "/problems/role-in-use"
        assert response.json()["holders"] == ["Omar Khalil"]

    def test_a_role_nobody_holds_is_deleted(self, admin: TestClient, unique: str) -> None:
        role = made(admin, f"Unused {unique}", [])

        response = admin.delete(f"/v1/roles/{role['id']}", headers=SAME_ORIGIN)

        assert response.status_code == 204
        assert admin.get(f"/v1/roles/{role['id']}", headers=SAME_ORIGIN).status_code == 404
