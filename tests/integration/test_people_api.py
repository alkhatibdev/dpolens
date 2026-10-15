"""People from the dashboard: adding them, their roles, deactivating them, sign-in links,
and changing one's own password.

In databases of their own: people and governance entries are never deleted, and
the lockout guard is a question about the whole instance.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, create_engine, select, update

from dpolens.api.app import create_app
from dpolens.api.dependencies import SESSION_COOKIE
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.models import Role, SignInLink, User
from dpolens.engine.auth.passwords import set_password
from dpolens.engine.auth.roles import create_role
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user
from dpolens.engine.logs.governance import (
    USER_PASSWORD_SET,
    USER_ROLE_GRANTED,
    USER_ROLE_REVOKED,
    USER_SIGN_IN_LINK_CREATED,
    Actor,
)
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a kettle on the third shelf"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
ADMIN = "admin-people@example.com"
PEOPLE_MANAGER = "People manager"


def instance(
    database_of_its_own: Callable[[str], tuple[str, str]], name: str
) -> Iterator[tuple[str, Engine]]:
    app_url, owner_url = database_of_its_own(name)
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
    add(opened_engine=owner, email=ADMIN, roles=(catalog.ADMIN,), name="Yousef Haddad")
    yield app_url, owner
    owner.dispose()


def add(
    *,
    opened_engine: Engine,
    email: str,
    roles: tuple[str, ...],
    name: str = "Some One",
    password: str | None = PASSWORD,
    kind: str = "person",
) -> str:
    """A person by email, with a password unless told otherwise, and their id."""
    with session_from(opened_engine) as opened:
        user = create_user(
            opened, email=email, display_name=name, actor=ACTOR, roles=roles, kind=kind
        )
        opened.flush()
        if password is not None:
            set_password(opened, email=email, password=password, actor=ACTOR)
        return str(user.id)


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    yield from instance(database_of_its_own, "dpolens_people")


@pytest.fixture
def owner(own: tuple[str, Engine]) -> Engine:
    return own[1]


@pytest.fixture(scope="module")
def app_client(own: tuple[str, Engine]) -> Iterator[TestClient]:
    app = create_app(Settings.model_validate({"database_url": own[0]}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def browser(app_client: TestClient) -> TestClient:
    app_client.cookies.clear()
    return app_client


def signed_in(browser: TestClient, email: str, password: str = PASSWORD) -> TestClient:
    browser.cookies.clear()
    response = browser.post(
        "/v1/sessions", json={"email": email, "password": password}, headers=SAME_ORIGIN
    )
    assert response.status_code == 201, response.text
    return browser


def entries(owner: Engine, action: str, target_id: str) -> list[GovernanceEntry]:
    with session_from(owner) as opened:
        rows = opened.scalars(
            select(GovernanceEntry)
            .where(GovernanceEntry.action == action, GovernanceEntry.target_id == target_id)
            .order_by(GovernanceEntry.seq)
        ).all()
        opened.expunge_all()
        return list(rows)


def admin_id(owner: Engine) -> str:
    with session_from(owner) as opened:
        return str(opened.scalars(select(User.id).where(User.email == ADMIN)).one())


class TestListingPeople:
    def test_it_needs_users_manage(self, browser: TestClient, owner: Engine, unique: str) -> None:
        email = f"dev-{unique}@example.com"
        add(opened_engine=owner, email=email, roles=(catalog.DEVELOPER,))

        response = signed_in(browser, email).get("/v1/users", headers=SAME_ORIGIN)

        assert response.status_code == 403
        assert response.json()["permission"] == catalog.USERS_MANAGE

    def test_everyone_is_listed_with_what_the_page_needs(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"listed-{unique}@example.com"
        add(opened_engine=owner, email=email, roles=(catalog.DEVELOPER,), name="Omar Khalil")
        with session_from(owner) as opened:
            mint(
                opened,
                email=email,
                name="laptop",
                permissions=[catalog.DOCUMENTS_READ],
                actor=ACTOR,
            )

        response = signed_in(browser, ADMIN).get("/v1/users", headers=SAME_ORIGIN)

        assert response.status_code == 200
        listed = {person["email"]: person for person in response.json()["people"]}
        assert listed[email]["display_name"] == "Omar Khalil"
        assert listed[email]["roles"] == [catalog.DEVELOPER]
        assert listed[email]["status"] == "active"
        assert listed[email]["has_password"] is True
        assert listed[email]["working_tokens"] == 1
        assert listed[email]["sign_in_link_expires_at"] is None


class TestTheAccountASurfaceActsThrough:
    def test_it_is_marked_so_the_page_can_leave_it_alone(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"surface-{unique}@surface.invalid"
        add(
            opened_engine=owner,
            email=email,
            roles=(),
            password=None,
            kind="service_account",
            name="MCP server",
        )
        with session_from(owner) as opened:
            mint(
                opened,
                email=email,
                name="mcp",
                permissions=[],
                actor=ACTOR,
                trusted_surface=True,
            )

        listed = {
            person["email"]: person
            for person in signed_in(browser, ADMIN)
            .get("/v1/users", headers=SAME_ORIGIN)
            .json()["people"]
        }

        assert listed[email]["acts_for_others"] is True
        assert listed[ADMIN]["acts_for_others"] is False


class TestAddingSomeone:
    def test_a_person_is_added_with_roles_and_no_password(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"Lina-{unique}@Example.com"

        response = signed_in(browser, ADMIN).post(
            "/v1/users",
            json={"email": email, "display_name": "Lina Farouk", "roles": [catalog.DPO]},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["email"] == email.lower()
        assert body["roles"] == [catalog.DPO]
        assert body["kind"] == "person"
        assert body["has_password"] is False
        created = entries(owner, "user.created", body["id"])
        assert str(created[0].actor_user_id) == admin_id(owner)
        assert created[0].details["via"] == "dashboard"

    def test_an_address_already_taken_is_refused(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"taken-{unique}@example.com"
        add(opened_engine=owner, email=email, roles=())

        response = signed_in(browser, ADMIN).post(
            "/v1/users", json={"email": email, "display_name": "Again"}, headers=SAME_ORIGIN
        )

        assert response.status_code == 409
        assert response.json()["type"] == "/problems/already-exists"

    def test_a_role_that_does_not_exist_is_refused(self, browser: TestClient, unique: str) -> None:
        response = signed_in(browser, ADMIN).post(
            "/v1/users",
            json={"email": f"x-{unique}@example.com", "display_name": "X", "roles": ["Auditor"]},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 400
        assert "Auditor" in response.json()["detail"]


class TestDeactivating:
    def test_someone_is_deactivated_and_reactivated(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"leaving-{unique}@example.com"
        person = add(opened_engine=owner, email=email, roles=(catalog.DEVELOPER,))
        admin = signed_in(browser, ADMIN)

        gone = admin.patch(
            f"/v1/users/{person}", json={"status": "deactivated"}, headers=SAME_ORIGIN
        )
        back = admin.patch(f"/v1/users/{person}", json={"status": "active"}, headers=SAME_ORIGIN)

        assert gone.status_code == 200
        assert gone.json()["status"] == "deactivated"
        assert gone.json()["deactivated_at"] is not None
        assert back.json()["status"] == "active"
        assert back.json()["deactivated_at"] is None

    def test_an_unknown_id_is_not_found(self, browser: TestClient) -> None:
        response = signed_in(browser, ADMIN).patch(
            "/v1/users/00000000-0000-4000-8000-000000000000",
            json={"status": "deactivated"},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 404


class TestChangingRoles:
    def test_roles_are_set_exactly_with_one_entry_each(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        person = add(
            opened_engine=owner, email=f"roles-{unique}@example.com", roles=(catalog.DEVELOPER,)
        )

        response = signed_in(browser, ADMIN).put(
            f"/v1/users/{person}/roles", json={"roles": [catalog.DPO]}, headers=SAME_ORIGIN
        )

        assert response.status_code == 200
        assert response.json()["roles"] == [catalog.DPO]
        assert [entry.details["role"] for entry in entries(owner, USER_ROLE_GRANTED, person)] == [
            catalog.DPO
        ]
        assert [entry.details["role"] for entry in entries(owner, USER_ROLE_REVOKED, person)] == [
            catalog.DEVELOPER
        ]


class TestNobodyGainsWhatTheyDoNotHold:
    """Someone who manages people but not everything cannot reach further through others."""

    @pytest.fixture
    def manager(self, owner: Engine, unique: str) -> str:
        with session_from(owner) as opened:
            if not opened.scalars(select(Role).where(Role.name == PEOPLE_MANAGER)).first():
                create_role(
                    opened,
                    name=PEOPLE_MANAGER,
                    actor=ACTOR,
                    permissions=(
                        catalog.USERS_MANAGE,
                        catalog.DOCUMENTS_READ,
                        catalog.QUERIES_READ_OWN,
                        catalog.TOKENS_CREATE,
                    ),
                )
        email = f"manager-{unique}@example.com"
        add(opened_engine=owner, email=email, roles=(PEOPLE_MANAGER,))
        return email

    def test_a_role_carrying_more_than_the_giver_holds_is_refused(
        self, browser: TestClient, owner: Engine, manager: str, unique: str
    ) -> None:
        person = add(opened_engine=owner, email=f"target-{unique}@example.com", roles=())

        response = signed_in(browser, manager).put(
            f"/v1/users/{person}/roles", json={"roles": [catalog.ADMIN]}, headers=SAME_ORIGIN
        )

        assert response.status_code == 403
        assert response.json()["permission"] == catalog.DOCUMENTS_PUBLISH

    def test_a_role_within_what_the_giver_holds_is_given(
        self, browser: TestClient, owner: Engine, manager: str, unique: str
    ) -> None:
        person = add(opened_engine=owner, email=f"dev2-{unique}@example.com", roles=())

        response = signed_in(browser, manager).put(
            f"/v1/users/{person}/roles", json={"roles": [catalog.DEVELOPER]}, headers=SAME_ORIGIN
        )

        assert response.status_code == 200

    def test_a_link_for_someone_who_holds_more_is_refused(
        self, browser: TestClient, owner: Engine, manager: str
    ) -> None:
        response = signed_in(browser, manager).post(
            f"/v1/users/{admin_id(owner)}/sign-in-links", headers=SAME_ORIGIN
        )

        assert response.status_code == 403


class TestSignInLinks:
    def make(self, browser: TestClient, person: str) -> str:
        response = signed_in(browser, ADMIN).post(
            f"/v1/users/{person}/sign-in-links", headers=SAME_ORIGIN
        )
        assert response.status_code == 201, response.text
        expires = datetime.fromisoformat(response.json()["expires_at"])
        assert timedelta(hours=71) < expires - datetime.now(UTC) <= timedelta(hours=72)
        secret: str = response.json()["secret"]
        return secret

    def spend(self, browser: TestClient, secret: str, password: str = NEW_PASSWORD) -> Response:
        browser.cookies.clear()
        return browser.post(
            "/v1/sessions/from-link",
            json={"secret": secret, "password": password},
            headers=SAME_ORIGIN,
        )

    def test_a_new_person_chooses_a_password_and_is_signed_in(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"new-{unique}@example.com"
        person = add(opened_engine=owner, email=email, roles=(catalog.DEVELOPER,), password=None)
        secret = self.make(browser, person)

        response = self.spend(browser, secret)

        assert response.status_code == 201, response.text
        assert response.json()["account"]["email"] == email
        assert browser.cookies.get(SESSION_COOKIE)
        assert browser.get("/v1/sessions/current", headers=SAME_ORIGIN).status_code == 200
        assert signed_in(browser, email, NEW_PASSWORD)
        made = entries(owner, USER_SIGN_IN_LINK_CREATED, person)
        assert [str(entry.actor_user_id) for entry in made] == [admin_id(owner)]
        assert "secret" not in made[0].details
        password_set = entries(owner, USER_PASSWORD_SET, person)
        assert password_set[-1].details["method"] == "sign_in_link"
        assert str(password_set[-1].actor_user_id) == person

    def test_a_link_says_who_it_is_for_without_being_spent(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"greeted-{unique}@example.com"
        person = add(opened_engine=owner, email=email, roles=(), password=None, name="Lina Farouk")
        secret = self.make(browser, person)
        browser.cookies.clear()

        looked = browser.post(
            "/v1/sign-in-links/lookup", json={"secret": secret}, headers=SAME_ORIGIN
        )

        assert looked.status_code == 200
        assert looked.json()["display_name"] == "Lina Farouk"
        assert looked.json()["email"] == email
        assert self.spend(browser, secret).status_code == 201
        after = browser.post(
            "/v1/sign-in-links/lookup", json={"secret": secret}, headers=SAME_ORIGIN
        )
        assert after.status_code == 410

    def test_a_link_works_once(self, browser: TestClient, owner: Engine, unique: str) -> None:
        person = add(
            opened_engine=owner, email=f"once-{unique}@example.com", roles=(), password=None
        )
        secret = self.make(browser, person)
        self.spend(browser, secret)

        again = self.spend(browser, secret, "another long password")

        assert again.status_code == 410
        assert again.json()["type"] == "/problems/sign-in-link-unusable"

    def test_a_newer_link_ends_the_older_one(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        person = add(
            opened_engine=owner, email=f"newer-{unique}@example.com", roles=(), password=None
        )
        older = self.make(browser, person)
        newer = self.make(browser, person)

        assert self.spend(browser, older).status_code == 410
        assert self.spend(browser, newer).status_code == 201

    def test_a_link_past_its_time_no_longer_works(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        person = add(
            opened_engine=owner, email=f"late-{unique}@example.com", roles=(), password=None
        )
        secret = self.make(browser, person)
        with session_from(owner) as opened:
            opened.execute(
                update(SignInLink)
                .where(SignInLink.user_id == person)
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )

        assert self.spend(browser, secret).status_code == 410

    def test_a_password_too_short_leaves_the_link_working(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        person = add(
            opened_engine=owner, email=f"short-{unique}@example.com", roles=(), password=None
        )
        secret = self.make(browser, person)

        short = self.spend(browser, secret, "too short")

        assert short.status_code == 422
        assert short.json()["type"] == "/problems/weak-password"
        assert self.spend(browser, secret).status_code == 201

    def test_the_old_password_works_until_the_link_is_used(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"forgot-{unique}@example.com"
        person = add(opened_engine=owner, email=email, roles=())
        self.make(browser, person)

        assert signed_in(browser, email, PASSWORD)

    def test_a_deactivated_persons_link_stops_working(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        person = add(
            opened_engine=owner, email=f"off-{unique}@example.com", roles=(), password=None
        )
        secret = self.make(browser, person)
        signed_in(browser, ADMIN).patch(
            f"/v1/users/{person}", json={"status": "deactivated"}, headers=SAME_ORIGIN
        )

        assert self.spend(browser, secret).status_code == 410

    def test_a_service_account_gets_no_link(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        account = add(
            opened_engine=owner,
            email=f"ci-{unique}@example.com",
            roles=(),
            password=None,
            kind="service_account",
        )

        response = signed_in(browser, ADMIN).post(
            f"/v1/users/{account}/sign-in-links", headers=SAME_ORIGIN
        )

        assert response.status_code == 400

    def test_spending_a_link_has_to_come_from_the_dashboards_own_pages(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        person = add(opened_engine=owner, email=f"xs-{unique}@example.com", roles=(), password=None)
        secret = self.make(browser, person)
        browser.cookies.clear()

        response = browser.post(
            "/v1/sessions/from-link", json={"secret": secret, "password": NEW_PASSWORD}
        )

        assert response.status_code == 403
        assert response.json()["type"] == "/problems/cross-site-request"

    def test_the_people_list_says_when_a_link_runs_out(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"waiting-{unique}@example.com"
        person = add(opened_engine=owner, email=email, roles=(), password=None)
        self.make(browser, person)

        listed = {
            entry["email"]: entry
            for entry in signed_in(browser, ADMIN)
            .get("/v1/users", headers=SAME_ORIGIN)
            .json()["people"]
        }

        assert listed[email]["has_password"] is False
        assert listed[email]["sign_in_link_expires_at"] is not None


class TestChangingOnesOwnPassword:
    def test_the_other_sessions_end_and_this_one_stays(
        self, app_client: TestClient, own: tuple[str, Engine], owner: Engine, unique: str
    ) -> None:
        email = f"change-{unique}@example.com"
        person = add(opened_engine=owner, email=email, roles=(catalog.DEVELOPER,))
        elsewhere = TestClient(app_client.app, base_url="https://testserver")
        signed_in(elsewhere, email)
        here = signed_in(app_client, email)

        response = here.put(
            "/v1/sessions/current/password",
            json={"current": PASSWORD, "new": NEW_PASSWORD},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 204, response.text
        assert here.get("/v1/sessions/current", headers=SAME_ORIGIN).status_code == 200
        ended = elsewhere.get("/v1/sessions/current", headers=SAME_ORIGIN)
        assert ended.status_code == 401
        assert entries(owner, USER_PASSWORD_SET, person)[-1].details["method"] == "current_password"

    def test_a_wrong_current_password_is_refused_without_signing_out(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"typo-{unique}@example.com"
        add(opened_engine=owner, email=email, roles=())
        signed_in(browser, email)

        response = browser.put(
            "/v1/sessions/current/password",
            json={"current": "not the password", "new": NEW_PASSWORD},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 403
        assert response.json()["type"] == "/problems/wrong-password"
        assert browser.get("/v1/sessions/current", headers=SAME_ORIGIN).status_code == 200

    def test_guessing_the_current_password_is_throttled(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"guess-{unique}@example.com"
        add(opened_engine=owner, email=email, roles=())
        signed_in(browser, email)
        for _ in range(5):
            browser.put(
                "/v1/sessions/current/password",
                json={"current": "a wrong guess", "new": NEW_PASSWORD},
                headers=SAME_ORIGIN,
            )

        response = browser.put(
            "/v1/sessions/current/password",
            json={"current": PASSWORD, "new": NEW_PASSWORD},
            headers=SAME_ORIGIN,
        )

        assert response.status_code == 429

    def test_a_token_cannot_change_a_password(
        self, browser: TestClient, owner: Engine, unique: str
    ) -> None:
        email = f"bytoken-{unique}@example.com"
        add(opened_engine=owner, email=email, roles=(catalog.DEVELOPER,))
        with session_from(owner) as opened:
            _, token = mint(
                opened, email=email, name="t", permissions=[catalog.DOCUMENTS_READ], actor=ACTOR
            )
        browser.cookies.clear()

        response = browser.put(
            "/v1/sessions/current/password",
            json={"current": PASSWORD, "new": NEW_PASSWORD},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403
        assert response.json()["type"] == "/problems/session-required"


@pytest.fixture(scope="module")
def alone(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    """An instance whose only administrator is the one signed in."""
    yield from instance(database_of_its_own, "dpolens_people_alone")


@pytest.fixture(scope="module")
def lone_client(alone: tuple[str, Engine]) -> Iterator[TestClient]:
    app = create_app(Settings.model_validate({"database_url": alone[0]}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


class TestTheLockoutGuard:
    """In an instance whose only administrator is the one signed in."""

    def test_the_last_administrator_cannot_be_deactivated(
        self, lone_client: TestClient, alone: tuple[str, Engine]
    ) -> None:
        response = signed_in(lone_client, ADMIN).patch(
            f"/v1/users/{admin_id(alone[1])}", json={"status": "deactivated"}, headers=SAME_ORIGIN
        )

        assert response.status_code == 409
        assert response.json()["type"] == "/problems/lockout-refused"
        assert catalog.ROLES_MANAGE in response.json()["detail"]

    def test_the_last_administrator_cannot_lose_the_role(
        self, lone_client: TestClient, alone: tuple[str, Engine]
    ) -> None:
        response = signed_in(lone_client, ADMIN).put(
            f"/v1/users/{admin_id(alone[1])}/roles", json={"roles": []}, headers=SAME_ORIGIN
        )

        assert response.status_code == 409
        assert response.json()["type"] == "/problems/lockout-refused"
