"""The API's door: what gets in, what is refused, and what the refusal says.

Nothing here searches anything. This is the part every route depends on: a
token, the permissions it carries this second, an assertion from a surface, a
limit, and one error shape.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from dpolens.api import limits
from dpolens.api.app import REQUEST_ID_HEADER, create_app
from dpolens.api.dependencies import ON_BEHALF_OF_TOKEN, ON_BEHALF_OF_USER
from dpolens.api.problems import MEDIA_TYPE
from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.tokens import mint, revoke
from dpolens.engine.auth.users import create_user, deactivate
from dpolens.engine.logs.governance import PAT_REJECTED, Actor, read_entries
from dpolens.engine.session import session_from
from dpolens.settings import Settings

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
INTROSPECT = "/v1/tokens/introspect"


@pytest.fixture(scope="module")
def api(committed_database_url: str) -> Iterator[TestClient]:
    """The real app on the database the committing tests use.

    The app opens its own engine in its lifespan, which is the behaviour under
    test: one engine for the process, one session per request.
    """
    app: FastAPI = create_app(Settings.model_validate({"database_url": committed_database_url}))
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def db(committed_database_url: str) -> Iterator[Engine]:
    from sqlalchemy import create_engine

    engine = create_engine(committed_database_url)
    with session_from(engine) as opened:
        bootstrap(opened, actor=ACTOR)
    yield engine
    engine.dispose()


@pytest.fixture
def opened(db: Engine) -> Iterator[Session]:
    """A session that commits, because the API reads what these tests write."""
    with session_from(db) as session:
        yield session


def a_token(
    session: Session,
    unique: str,
    *,
    permissions: tuple[str, ...] = (catalog.DOCUMENTS_READ,),
    role: str = catalog.DEVELOPER,
    label: str = "api",
    **overrides: object,
) -> tuple[str, str]:
    """A user and one of their tokens, returning the secret and the owner's email."""
    email = f"api-{label}-{unique}@example.com"
    create_user(session, email=email, display_name="API user", actor=ACTOR, roles=(role,))
    session.flush()
    _, token = mint(
        session,
        email=email,
        name=label,
        permissions=permissions,
        actor=ACTOR,
        **overrides,  # type: ignore[arg-type]
    )
    return token, email


class TestProbes:
    def test_liveness_needs_no_credential_and_no_database(self, api: TestClient) -> None:
        response = api.get("/live")

        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_readiness_reports_the_database(self, api: TestClient) -> None:
        response = api.get("/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    def test_neither_says_anything_about_the_build(self, api: TestClient) -> None:
        """An unauthenticated endpoint is the one an attacker can always reach."""
        for path in ("/live", "/ready"):
            body = api.get(path).text
            assert "dpolens" not in body.lower()
            assert "postgres" not in body.lower()


class TestRequestId:
    def test_a_uuid_from_the_client_is_kept(self, api: TestClient) -> None:
        """So one developer's question can be followed across two calls."""
        given = str(uuid.uuid4())

        response = api.get("/live", headers={REQUEST_ID_HEADER: given})

        assert response.headers[REQUEST_ID_HEADER] == given

    def test_something_that_is_not_a_uuid_is_replaced(self, api: TestClient) -> None:
        """Which is also what stops a caller writing newlines into telemetry."""
        response = api.get("/live", headers={REQUEST_ID_HEADER: "not a uuid\nlevel=error"})

        returned = response.headers[REQUEST_ID_HEADER]
        assert returned != "not a uuid\nlevel=error"
        assert uuid.UUID(returned)

    def test_one_is_minted_when_none_is_sent(self, api: TestClient) -> None:
        assert uuid.UUID(api.get("/live").headers[REQUEST_ID_HEADER])


class TestWhoIsRefused:
    def test_no_credential_at_all(self, api: TestClient) -> None:
        response = api.post(INTROSPECT, json={"token": "dpol_whatever"})

        assert response.status_code == 401
        assert response.headers["content-type"].startswith(MEDIA_TYPE)
        assert response.headers["WWW-Authenticate"] == "Bearer"
        body = response.json()
        assert body["type"] == "/problems/unauthenticated"
        assert body["status"] == 401
        assert body["instance"] == INTROSPECT
        assert "code" not in body

    def test_a_credential_in_the_wrong_scheme(self, api: TestClient) -> None:
        response = api.post(
            INTROSPECT, json={"token": "dpol_x"}, headers={"Authorization": "Basic abc"}
        )

        assert response.status_code == 401
        assert "Bearer" in response.json()["detail"]

    def test_an_unknown_token_says_nothing_about_why(self, api: TestClient) -> None:
        response = api.post(
            INTROSPECT,
            json={"token": "dpol_x"},
            headers={"Authorization": "Bearer dpol_thisdoesnotexistanywhere"},
        )

        assert response.status_code == 401
        assert response.json()["type"] == "/problems/unauthenticated"

    def test_a_revoked_token_is_named_as_refused_and_recorded(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        """A token with an owner is the leak signal, so it goes in the log."""
        token, _ = a_token(opened, unique, permissions=(catalog.DOCUMENTS_READ,))
        opened.commit()
        row = revoke(opened, prefix=token[:11], actor=ACTOR)
        opened.commit()
        before = len(read_entries(opened))

        response = api.post(
            INTROSPECT, json={"token": token}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        body = response.json()
        assert body["type"] == "/problems/token-refused"
        assert body["reason"] == "revoked"

        opened.expire_all()
        added = read_entries(opened)[before:]
        assert [entry.action for entry in added] == [PAT_REJECTED]
        assert str(row.id) in added[0].target_id

    def test_a_token_whose_owner_left(self, api: TestClient, opened: Session, unique: str) -> None:
        create_user(
            opened,
            email=f"keeper-{unique}@example.com",
            display_name="Keeper",
            actor=ACTOR,
            roles=(catalog.ADMIN,),
        )
        token, email = a_token(opened, unique, label="leaver")
        opened.commit()
        deactivate(opened, email=email, actor=ACTOR)
        opened.commit()

        response = api.post(
            INTROSPECT, json={"token": token}, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert response.json()["reason"] == "owner_inactive"


class TestIntrospection:
    def test_only_a_trusted_surface_may_ask(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        """Otherwise the API becomes a way to test other people's tokens."""
        ordinary, _ = a_token(opened, unique)
        opened.commit()

        response = api.post(
            INTROSPECT, json={"token": ordinary}, headers={"Authorization": f"Bearer {ordinary}"}
        )

        assert response.status_code == 403
        assert response.json()["type"] == "/problems/delegation-not-permitted"

    def test_a_surface_learns_who_is_calling_and_what_they_may_do(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        surface, _ = a_token(opened, unique, label="surface", trusted_surface=True)
        developer, email = a_token(
            opened,
            unique,
            label="dev",
            permissions=(catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN),
        )
        opened.commit()

        response = api.post(
            INTROSPECT, json={"token": developer}, headers={"Authorization": f"Bearer {surface}"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["active"] is True
        assert body["email"] == email
        assert body["permissions"] == [catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN]

    def test_an_unusable_token_is_inactive_rather_than_an_error(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        """The surface only needs to know it cannot act for this caller."""
        surface, _ = a_token(opened, unique, label="surface", trusted_surface=True)
        opened.commit()

        response = api.post(
            INTROSPECT,
            json={"token": "dpol_neverexisted"},
            headers={"Authorization": f"Bearer {surface}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "active": False,
            "user_id": None,
            "email": None,
            "pat_id": None,
            "permissions": [],
            "expires_at": None,
        }

    def test_a_body_without_a_token_is_a_problem_document_too(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        surface, _ = a_token(opened, unique, label="surface", trusted_surface=True)
        opened.commit()

        response = api.post(INTROSPECT, json={}, headers={"Authorization": f"Bearer {surface}"})

        assert response.status_code == 422
        assert response.headers["content-type"].startswith(MEDIA_TYPE)
        body = response.json()
        assert body["type"] == "/problems/invalid-request"
        assert body["errors"][0]["field"].endswith("token")


class TestActingForSomebodyElse:
    def test_an_ordinary_token_may_not_assert_an_identity(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        ordinary, _ = a_token(opened, unique)
        surface_token, _ = a_token(opened, unique, label="surface", trusted_surface=True)
        opened.commit()

        response = api.post(
            INTROSPECT,
            json={"token": ordinary},
            headers={
                "Authorization": f"Bearer {ordinary}",
                ON_BEHALF_OF_USER: str(uuid.uuid4()),
                ON_BEHALF_OF_TOKEN: str(uuid.uuid4()),
            },
        )

        assert response.status_code == 403
        assert response.json()["type"] == "/problems/delegation-not-permitted"
        assert surface_token

    def test_half_an_assertion_is_refused(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        surface, _ = a_token(opened, unique, label="surface", trusted_surface=True)
        opened.commit()

        response = api.post(
            INTROSPECT,
            json={"token": surface},
            headers={
                "Authorization": f"Bearer {surface}",
                ON_BEHALF_OF_USER: str(uuid.uuid4()),
            },
        )

        assert response.status_code == 400
        assert ON_BEHALF_OF_TOKEN in response.json()["detail"]

    def test_a_surface_cannot_invent_a_token_id(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        """The trust is that a surface may name the caller, not make one up."""
        surface, _ = a_token(opened, unique, label="surface", trusted_surface=True)
        opened.commit()

        response = api.post(
            INTROSPECT,
            json={"token": surface},
            headers={
                "Authorization": f"Bearer {surface}",
                ON_BEHALF_OF_USER: str(uuid.uuid4()),
                ON_BEHALF_OF_TOKEN: str(uuid.uuid4()),
            },
        )

        assert response.status_code == 401
        assert "does not belong" in response.json()["detail"]

    def test_a_token_that_belongs_to_another_user_is_refused(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        surface, _ = a_token(opened, unique, label="surface", trusted_surface=True)
        _, first_email = a_token(opened, unique, label="one")
        opened.commit()

        from dpolens.engine.auth.tokens import list_tokens
        from dpolens.engine.auth.users import get_user

        theirs = list_tokens(opened, email=first_email)[0]
        somebody_else = get_user(opened, f"api-surface-{unique}@example.com")

        response = api.post(
            INTROSPECT,
            json={"token": surface},
            headers={
                "Authorization": f"Bearer {surface}",
                ON_BEHALF_OF_USER: str(somebody_else.id),
                ON_BEHALF_OF_TOKEN: str(theirs.id),
            },
        )

        assert response.status_code == 401
        assert "does not belong" in response.json()["detail"]


class TestTheLimit:
    @pytest.fixture(autouse=True)
    def stopped_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The bucket earns a request back every second, so a burst that takes longer
        than that on a busy machine would be granted its last request."""
        monkeypatch.setattr(limits, "monotonic", lambda: 0.0)

    def test_a_token_that_spends_its_quota_is_told_when_to_return(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        surface, _ = a_token(opened, unique, label="surface", trusted_surface=True)
        opened.commit()
        limit = api.app.state.limiter.per_minute  # type: ignore[attr-defined]

        codes = [
            api.post(
                INTROSPECT, json={"token": surface}, headers={"Authorization": f"Bearer {surface}"}
            ).status_code
            for _ in range(limit + 1)
        ]

        assert codes[:limit] == [200] * limit
        assert codes[-1] == 429

        refused = api.post(
            INTROSPECT, json={"token": surface}, headers={"Authorization": f"Bearer {surface}"}
        )
        assert refused.status_code == 429
        assert int(refused.headers["Retry-After"]) >= 1
        assert refused.json()["type"] == "/problems/too-many-requests"
        # The draft RateLimit fields are deliberately not emitted.
        assert "RateLimit" not in refused.headers

    def test_another_token_is_unaffected(
        self, api: TestClient, opened: Session, unique: str
    ) -> None:
        """The limit is per token, so one runaway client does not stop the others."""
        spender, _ = a_token(opened, unique, label="spender", trusted_surface=True)
        other, _ = a_token(opened, unique, label="other", trusted_surface=True)
        opened.commit()
        limit = api.app.state.limiter.per_minute  # type: ignore[attr-defined]

        for _ in range(limit + 1):
            api.post(
                INTROSPECT, json={"token": spender}, headers={"Authorization": f"Bearer {spender}"}
            )

        response = api.post(
            INTROSPECT, json={"token": other}, headers={"Authorization": f"Bearer {other}"}
        )
        assert response.status_code == 200


def test_using_a_token_records_that_it_was_used(
    api: TestClient, opened: Session, unique: str
) -> None:
    surface, _ = a_token(opened, unique, label="surface", trusted_surface=True)
    opened.commit()

    api.post(INTROSPECT, json={"token": surface}, headers={"Authorization": f"Bearer {surface}"})

    from dpolens.engine.auth.tokens import find

    opened.expire_all()
    assert find(opened, surface[:11]).last_used_at is not None
