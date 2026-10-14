"""Signing in to the dashboard, and what a session may and may not do.

In a database of its own: users, sessions and governance entries are never
deleted, and other modules count them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select

from dpolens.api.app import create_app
from dpolens.api.dependencies import PLAIN_HTTP_SESSION_COOKIE, SESSION_COOKIE
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.models import DashboardSession, User
from dpolens.engine.auth.passwords import NoPasswordAllowed, set_password
from dpolens.engine.auth.sessions import (
    Lifetimes,
    SessionEnded,
    SignInRefused,
    purge_ended,
    resolve,
    sign_in,
)
from dpolens.engine.auth.tokens import mint
from dpolens.engine.auth.users import create_user, deactivate
from dpolens.engine.logs.governance import (
    SESSION_ENDED,
    SESSION_REFUSED,
    SESSION_STARTED,
    USER_PASSWORD_SET,
    Actor,
)
from dpolens.engine.logs.models import GovernanceEntry, QueryLogEntry
from dpolens.engine.packs.load import load_pack
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
PASSWORD = "correct horse battery staple"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
LIFETIMES = Lifetimes(idle=timedelta(minutes=30), absolute=timedelta(hours=8))
FIXTURE_PACKS = Path(__file__).parents[1] / "fixtures" / "packs"


@pytest.fixture(scope="module")
def own(database_of_its_own: Callable[[str], tuple[str, str]]) -> Iterator[tuple[str, Engine]]:
    app_url, owner_url = database_of_its_own("dpolens_sessions")
    owner = create_engine(owner_url)
    with session_from(owner) as opened:
        bootstrap(opened, actor=ACTOR)
        load_pack(opened, FIXTURE_PACKS / "testlaw")
    yield app_url, owner
    owner.dispose()


@pytest.fixture
def owner(own: tuple[str, Engine]) -> Engine:
    return own[1]


@pytest.fixture
def person(owner: Engine, unique: str) -> str:
    """A developer with a password, by email address."""
    email = f"session-{unique}@example.com"
    with session_from(owner) as opened:
        create_user(
            opened, email=email, display_name="Signed In", actor=ACTOR, roles=(catalog.DEVELOPER,)
        )
        opened.flush()
        set_password(opened, email=email, password=PASSWORD, actor=ACTOR)
    return email


@pytest.fixture(scope="module")
def app_client(own: tuple[str, Engine]) -> Iterator[TestClient]:
    """Over HTTPS, as a browser would reach a real instance: the cookie is Secure."""
    app = create_app(Settings.model_validate({"database_url": own[0]}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def browser(app_client: TestClient) -> TestClient:
    """The same app, holding no cookie from an earlier test."""
    app_client.cookies.clear()
    return app_client


def signed_in(browser: TestClient, email: str) -> str:
    response = browser.post(
        "/v1/sessions", json={"email": email, "password": PASSWORD}, headers=SAME_ORIGIN
    )
    assert response.status_code == 201, response.text
    secret = browser.cookies.get(SESSION_COOKIE)
    assert secret
    return secret


def user_id(owner: Engine, email: str) -> str:
    with session_from(owner) as opened:
        return str(opened.scalars(select(User.id).where(User.email == email)).one())


def entries(owner: Engine, action: str, target_id: str) -> list[GovernanceEntry]:
    with session_from(owner) as opened:
        rows = opened.scalars(
            select(GovernanceEntry)
            .where(GovernanceEntry.action == action, GovernanceEntry.target_id == target_id)
            .order_by(GovernanceEntry.seq)
        ).all()
        opened.expunge_all()
        return list(rows)


class TestSigningIn:
    def test_a_right_password_opens_a_session_the_pages_scripts_cannot_read(
        self, browser: TestClient, person: str
    ) -> None:
        response = browser.post(
            "/v1/sessions", json={"email": person, "password": PASSWORD}, headers=SAME_ORIGIN
        )

        assert response.status_code == 201, response.text
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{SESSION_COOKIE}=")
        for attribute in ("HttpOnly", "Secure", "Path=/"):
            assert attribute in cookie
        assert "samesite=strict" in cookie.lower()
        assert "Domain" not in cookie

        body = response.json()
        assert body["account"] == {
            "email": person,
            "display_name": "Signed In",
            "roles": [catalog.DEVELOPER],
        }
        assert catalog.DOCUMENTS_READ in body["permissions"]
        assert body["idle_minutes"] == 30

    def test_a_browser_on_plain_http_gets_a_cookie_it_will_keep(
        self, browser: TestClient, person: str
    ) -> None:
        """Safari keeps no Secure cookie on http://localhost, and on plain HTTP the
        flag protects nothing, so the cookie follows the scheme the page was on."""
        response = browser.post(
            "/v1/sessions",
            json={"email": person, "password": PASSWORD},
            headers={**SAME_ORIGIN, "Origin": "http://localhost:8080"},
        )

        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{PLAIN_HTTP_SESSION_COOKIE}=")
        assert "Secure" not in cookie
        assert "HttpOnly" in cookie
        assert "samesite=strict" in cookie.lower()
        assert browser.get("/v1/sessions/current", headers=SAME_ORIGIN).status_code == 200

    def test_a_browser_on_https_gets_the_strict_cookie(
        self, browser: TestClient, person: str
    ) -> None:
        response = browser.post(
            "/v1/sessions",
            json={"email": person, "password": PASSWORD},
            headers={**SAME_ORIGIN, "Origin": "https://dpolens.example.com"},
        )

        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{SESSION_COOKIE}=")
        assert "Secure" in cookie

    def test_a_wrong_password_and_an_unknown_address_get_the_same_answer(
        self, browser: TestClient, person: str, unique: str
    ) -> None:
        wrong = browser.post(
            "/v1/sessions",
            json={"email": person, "password": "not the password"},
            headers=SAME_ORIGIN,
        )
        unknown = browser.post(
            "/v1/sessions",
            json={"email": f"nobody-{unique}@example.com", "password": PASSWORD},
            headers=SAME_ORIGIN,
        )

        for response in (wrong, unknown):
            assert response.status_code == 401
            assert response.json()["type"] == "/problems/sign-in-refused"
        assert wrong.json()["detail"] == unknown.json()["detail"]
        assert SESSION_COOKIE not in browser.cookies

    def test_a_wrong_password_for_a_real_account_is_written_to_the_governance_log(
        self, browser: TestClient, person: str, owner: Engine
    ) -> None:
        browser.post(
            "/v1/sessions",
            json={"email": person, "password": "not the password"},
            headers=SAME_ORIGIN,
        )

        refused = entries(owner, SESSION_REFUSED, user_id(owner, person))
        assert [entry.details["reason"] for entry in refused] == ["wrong_password"]

    def test_five_failures_make_an_address_wait_even_with_the_right_password(
        self, browser: TestClient, person: str
    ) -> None:
        for _ in range(5):
            browser.post(
                "/v1/sessions",
                json={"email": person, "password": "wrong guess"},
                headers=SAME_ORIGIN,
            )

        response = browser.post(
            "/v1/sessions", json={"email": person, "password": PASSWORD}, headers=SAME_ORIGIN
        )

        assert response.status_code == 429
        assert response.json()["type"] == "/problems/too-many-attempts"
        assert int(response.headers["Retry-After"]) > 0

    def test_signing_in_has_to_come_from_the_dashboards_own_pages(
        self, browser: TestClient, person: str
    ) -> None:
        for headers in ({}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
            response = browser.post(
                "/v1/sessions", json={"email": person, "password": PASSWORD}, headers=headers
            )
            assert response.status_code == 403
            assert response.json()["type"] == "/problems/cross-site-request"

    def test_a_deactivated_person_cannot_sign_in(
        self, browser: TestClient, person: str, owner: Engine
    ) -> None:
        with session_from(owner) as opened:
            deactivate(opened, email=person, actor=ACTOR)

        response = browser.post(
            "/v1/sessions", json={"email": person, "password": PASSWORD}, headers=SAME_ORIGIN
        )

        assert response.status_code == 401
        refused = entries(owner, SESSION_REFUSED, user_id(owner, person))
        assert refused[-1].details["reason"] == "not_active"


class TestASignedInBrowser:
    def test_the_session_says_who_is_signed_in(self, browser: TestClient, person: str) -> None:
        signed_in(browser, person)

        response = browser.get("/v1/sessions/current", headers=SAME_ORIGIN)

        assert response.status_code == 200
        assert response.json()["account"]["email"] == person

    def test_every_call_with_the_cookie_has_to_come_from_the_dashboard(
        self, browser: TestClient, person: str
    ) -> None:
        signed_in(browser, person)

        response = browser.get("/v1/documents")

        assert response.status_code == 403
        assert response.json()["type"] == "/problems/cross-site-request"

    def test_a_call_from_the_dashboard_is_logged_as_the_dashboard(
        self, browser: TestClient, person: str, owner: Engine
    ) -> None:
        signed_in(browser, person)

        response = browser.get("/v1/documents", headers=SAME_ORIGIN)

        assert response.status_code == 200
        with session_from(owner) as opened:
            logged = opened.scalars(
                select(QueryLogEntry)
                .where(QueryLogEntry.actor_user_id == user_id(owner, person))
                .order_by(QueryLogEntry.created_at.desc())
            ).first()
            assert logged is not None
            assert (logged.surface, logged.actor_pat_id) == ("dashboard", None)

    def test_a_document_says_whether_it_is_in_the_selected_laws(
        self, browser: TestClient, person: str
    ) -> None:
        signed_in(browser, person)

        documents = browser.get("/v1/documents", headers=SAME_ORIGIN).json()["documents"]
        detail = browser.get("/v1/documents/testlaw", headers=SAME_ORIGIN).json()["document"]

        assert documents
        assert all(document["in_selected_laws"] is True for document in documents)
        assert detail["in_selected_laws"] is True

    def test_signing_out_ends_the_session_and_clears_the_cookie(
        self, browser: TestClient, person: str, owner: Engine
    ) -> None:
        secret = signed_in(browser, person)

        response = browser.delete("/v1/sessions/current", headers=SAME_ORIGIN)

        assert response.status_code == 204
        assert SESSION_COOKIE not in browser.cookies
        browser.cookies.set(SESSION_COOKIE, secret)
        after = browser.get("/v1/sessions/current", headers=SAME_ORIGIN)
        assert after.status_code == 401
        assert after.json()["type"] == "/problems/session-ended"

    def test_a_deactivated_persons_session_stops_on_the_next_request(
        self, browser: TestClient, person: str, owner: Engine
    ) -> None:
        signed_in(browser, person)
        with session_from(owner) as opened:
            deactivate(opened, email=person, actor=ACTOR)

        response = browser.get("/v1/sessions/current", headers=SAME_ORIGIN)

        assert response.status_code == 401
        assert response.json()["reason"] == "owner_inactive"

    def test_a_token_in_the_header_wins_over_the_cookie(
        self, browser: TestClient, person: str, owner: Engine
    ) -> None:
        signed_in(browser, person)
        with session_from(owner) as opened:
            _, token = mint(
                opened,
                email=person,
                name="laptop",
                permissions=(catalog.DOCUMENTS_READ,),
                actor=ACTOR,
            )

        response = browser.get("/v1/sessions/current", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert "not a token" in response.json()["detail"]

    def test_a_session_cannot_ask_about_tokens(self, browser: TestClient, person: str) -> None:
        signed_in(browser, person)

        response = browser.post(
            "/v1/tokens/introspect", json={"token": "dpol_x"}, headers=SAME_ORIGIN
        )

        assert response.status_code == 403


class TestWhenASessionEnds:
    """With the clock given, rather than waited for."""

    def test_a_session_lasts_its_lifetime_however_much_it_is_used(
        self, owner: Engine, person: str
    ) -> None:
        start = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
        with session_from(owner) as opened:
            _, secret = sign_in(
                opened, email=person, password=PASSWORD, lifetimes=LIFETIMES, now=start
            )
            for minutes in range(20, 8 * 60, 20):
                resolve(opened, secret, lifetimes=LIFETIMES, now=start + timedelta(minutes=minutes))

            with pytest.raises(SessionEnded, match="expired"):
                resolve(opened, secret, lifetimes=LIFETIMES, now=start + timedelta(hours=8))

    def test_a_session_nobody_uses_ends_after_the_idle_timeout(
        self, owner: Engine, person: str
    ) -> None:
        start = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
        with session_from(owner) as opened:
            _, secret = sign_in(
                opened, email=person, password=PASSWORD, lifetimes=LIFETIMES, now=start
            )

            with pytest.raises(SessionEnded, match="idle"):
                resolve(opened, secret, lifetimes=LIFETIMES, now=start + timedelta(minutes=31))

    def test_last_seen_is_written_at_most_once_a_minute(self, owner: Engine, person: str) -> None:
        start = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
        with session_from(owner) as opened:
            row, secret = sign_in(
                opened, email=person, password=PASSWORD, lifetimes=LIFETIMES, now=start
            )
            resolve(opened, secret, lifetimes=LIFETIMES, now=start + timedelta(seconds=30))
            assert row.last_seen_at == start

            resolve(opened, secret, lifetimes=LIFETIMES, now=start + timedelta(seconds=61))
            assert row.last_seen_at == start + timedelta(seconds=61)

    def test_a_new_password_signs_a_person_out_everywhere(self, owner: Engine, person: str) -> None:
        with session_from(owner) as opened:
            for _ in range(2):
                sign_in(opened, email=person, password=PASSWORD, lifetimes=LIFETIMES)
        with session_from(owner) as opened:
            set_password(opened, email=person, password="a different passphrase", actor=ACTOR)

        with session_from(owner) as opened:
            left = opened.scalar(
                select(func.count())
                .select_from(DashboardSession)
                .join(User)
                .where(User.email == person)
            )
        assert left == 0
        changed = entries(owner, USER_PASSWORD_SET, user_id(owner, person))[-1]
        assert changed.details["sessions_ended"] == 2

    def test_sessions_that_can_no_longer_be_used_are_purged(
        self, owner: Engine, person: str
    ) -> None:
        long_ago = datetime(2020, 1, 1, tzinfo=UTC)
        with session_from(owner) as opened:
            sign_in(opened, email=person, password=PASSWORD, lifetimes=LIFETIMES, now=long_ago)
            current, _ = sign_in(opened, email=person, password=PASSWORD, lifetimes=LIFETIMES)

            assert purge_ended(opened, lifetimes=LIFETIMES) >= 1
            assert opened.get(DashboardSession, current.id) is not None

    def test_signing_in_and_out_are_governance_entries(
        self, browser: TestClient, person: str, owner: Engine
    ) -> None:
        signed_in(browser, person)
        browser.delete("/v1/sessions/current", headers=SAME_ORIGIN)

        with session_from(owner) as opened:
            actions = opened.scalars(
                select(GovernanceEntry.action)
                .where(GovernanceEntry.actor_user_id == user_id(owner, person))
                .order_by(GovernanceEntry.seq)
            ).all()
        assert list(actions) == [SESSION_STARTED, SESSION_ENDED]


def test_a_service_account_has_no_password(owner: Engine, unique: str) -> None:
    email = f"service-{unique}@example.com"
    with session_from(owner) as opened:
        create_user(opened, email=email, display_name="CI", actor=ACTOR, kind="service_account")
        opened.flush()
        with pytest.raises(NoPasswordAllowed):
            set_password(opened, email=email, password=PASSWORD, actor=ACTOR)


def test_an_unknown_address_is_refused_without_naming_an_account(owner: Engine) -> None:
    with session_from(owner) as opened, pytest.raises(SignInRefused) as refused:
        sign_in(opened, email="nobody@example.com", password=PASSWORD, lifetimes=LIFETIMES)

    assert refused.value.user is None
