"""Tokens against a real database: what authenticates, and what stops working when.

A token is the only credential in v0.1, so the cases that matter are the ones
where it must stop working: revoked, expired, an owner who left, a permission
taken away from the role behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.models import PersonalAccessToken
from dpolens.engine.auth.roles import UnknownPermission, revoke_permission
from dpolens.engine.auth.tokens import (
    AmbiguousPrefix,
    Authenticated,
    OwnerCannotHoldTokens,
    PermissionsExceedOwner,
    TokenNotFound,
    TokenRejected,
    UnknownToken,
    authenticate,
    find,
    generate,
    list_tokens,
    mint,
    revoke,
    status_of,
    touch,
)
from dpolens.engine.auth.users import create_user, deactivate, revoke_role
from dpolens.engine.logs.governance import PAT_CREATED, PAT_REVOKED, Actor, read_entries, record

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})
DEVELOPER_PERMISSIONS = catalog.SEEDED_ROLES[catalog.DEVELOPER]


@pytest.fixture
def ready(session: Session) -> Session:
    bootstrap(session, actor=ACTOR)
    session.flush()
    return session


def developer(session: Session, unique: str, suffix: str = "") -> str:
    user = create_user(
        session,
        email=f"dev{suffix}-{unique}@example.com",
        display_name="A developer",
        actor=ACTOR,
        roles=(catalog.DEVELOPER,),
    )
    session.flush()
    return user.email


def a_token(session: Session, unique: str, **overrides: object) -> tuple[PersonalAccessToken, str]:
    email = overrides.pop("email", None) or developer(session, unique)
    return mint(
        session,
        email=str(email),
        name=str(overrides.pop("name", "laptop")),
        permissions=overrides.pop("permissions", (catalog.DOCUMENTS_READ,)),  # type: ignore[arg-type]
        actor=ACTOR,
        **overrides,  # type: ignore[arg-type]
    )


class TestMinting:
    def test_a_token_authenticates_as_its_owner(self, ready: Session, unique: str) -> None:
        row, token = a_token(ready, unique)
        ready.flush()

        who = authenticate(ready, token)

        assert isinstance(who, Authenticated)
        assert who.user.id == row.user_id
        assert who.permissions == {catalog.DOCUMENTS_READ}
        assert who.may(catalog.DOCUMENTS_READ)
        assert not who.may(catalog.QUERIES_READ_ALL)

    def test_nothing_stores_the_token(self, ready: Session, unique: str) -> None:
        """The row keeps a digest and a prefix, and the digest is not reversible."""
        row, token = a_token(ready, unique)
        ready.flush()

        stored = (
            ready.execute(
                text("SELECT * FROM personal_access_tokens WHERE id = :id"), {"id": row.id}
            )
            .mappings()
            .one()
        )

        assert token not in str(dict(stored))
        assert stored["token_hash"] != token
        assert token.startswith(stored["prefix"])

    def test_a_permission_the_owner_does_not_hold_is_refused(
        self, ready: Session, unique: str
    ) -> None:
        email = developer(ready, unique)

        with pytest.raises(PermissionsExceedOwner) as raised:
            a_token(ready, unique, email=email, permissions=(catalog.QUERIES_READ_ALL,))

        assert catalog.QUERIES_READ_ALL in str(raised.value)
        assert email in str(raised.value)

    def test_a_permission_outside_the_catalog_is_refused(self, ready: Session, unique: str) -> None:
        email = developer(ready, unique)

        with pytest.raises(UnknownPermission):
            a_token(ready, unique, email=email, permissions=("documents.destroy",))

    def test_a_token_with_no_permissions_is_allowed_and_can_do_nothing(
        self, ready: Session, unique: str
    ) -> None:
        """Useful for checking that a client connects at all, and harmless."""
        _, token = a_token(ready, unique, permissions=())
        ready.flush()

        assert authenticate(ready, token).permissions == frozenset()

    def test_a_deactivated_owner_cannot_be_given_a_new_token(
        self, ready: Session, unique: str
    ) -> None:
        keeper = create_user(
            ready,
            email=f"admin-{unique}@example.com",
            display_name="Admin",
            actor=ACTOR,
            roles=(catalog.ADMIN,),
        )
        assert keeper
        email = developer(ready, unique)
        deactivate(ready, email=email, actor=ACTOR)
        ready.flush()

        with pytest.raises(OwnerCannotHoldTokens, match="deactivated"):
            a_token(ready, unique, email=email)


class TestWhatStopsWorking:
    def test_an_unknown_token_is_refused_without_saying_more(self, ready: Session) -> None:
        with pytest.raises(UnknownToken):
            authenticate(ready, generate()[0])

    def test_something_that_is_not_a_token_at_all(self, ready: Session) -> None:
        with pytest.raises(UnknownToken, match="not a DPOLens token"):
            authenticate(ready, "Bearer hunter2")

    def test_a_revoked_token(self, ready: Session, unique: str) -> None:
        row, token = a_token(ready, unique)
        ready.flush()
        revoke(ready, prefix=row.prefix, actor=ACTOR)
        ready.flush()

        with pytest.raises(TokenRejected) as raised:
            authenticate(ready, token)
        assert raised.value.reason == "revoked"
        assert raised.value.token.id == row.id

    def test_an_expired_token(self, ready: Session, unique: str) -> None:
        _, token = a_token(ready, unique, expires_at=datetime.now(UTC) - timedelta(seconds=1))
        ready.flush()

        with pytest.raises(TokenRejected) as raised:
            authenticate(ready, token)
        assert raised.value.reason == "expired"

    def test_a_token_expiring_in_the_future_still_works(self, ready: Session, unique: str) -> None:
        _, token = a_token(ready, unique, expires_at=datetime.now(UTC) + timedelta(days=1))
        ready.flush()

        assert authenticate(ready, token).permissions == {catalog.DOCUMENTS_READ}

    def test_an_owner_who_was_deactivated_after_the_token_was_made(
        self, ready: Session, unique: str
    ) -> None:
        create_user(
            ready,
            email=f"admin-{unique}@example.com",
            display_name="Admin",
            actor=ACTOR,
            roles=(catalog.ADMIN,),
        )
        email = developer(ready, unique)
        _, token = a_token(ready, unique, email=email)
        ready.flush()

        deactivate(ready, email=email, actor=ACTOR)
        ready.flush()

        with pytest.raises(TokenRejected) as raised:
            authenticate(ready, token)
        assert raised.value.reason == "owner_inactive"

    def test_revoking_one_token_leaves_the_others(self, ready: Session, unique: str) -> None:
        email = developer(ready, unique)
        first, first_token = a_token(ready, unique, email=email, name="laptop")
        _, second_token = a_token(ready, unique, email=email, name="ci")
        ready.flush()

        revoke(ready, prefix=first.prefix, actor=ACTOR)
        ready.flush()

        with pytest.raises(TokenRejected):
            authenticate(ready, first_token)
        assert authenticate(ready, second_token).permissions == {catalog.DOCUMENTS_READ}


class TestPermissionsNarrowByThemselves:
    def test_taking_the_permission_from_the_role_narrows_the_token(
        self, ready: Session, unique: str
    ) -> None:
        """Nothing rewrites the token, and there is no cache to wait out."""
        email = developer(ready, unique)
        _, token = a_token(
            ready,
            unique,
            email=email,
            permissions=(catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN),
        )
        ready.flush()
        assert authenticate(ready, token).permissions == {
            catalog.DOCUMENTS_READ,
            catalog.QUERIES_READ_OWN,
        }

        revoke_permission(
            ready, role_name=catalog.DEVELOPER, permission=catalog.QUERIES_READ_OWN, actor=ACTOR
        )
        ready.flush()

        assert authenticate(ready, token).permissions == {catalog.DOCUMENTS_READ}

    def test_taking_the_role_away_empties_the_token(self, ready: Session, unique: str) -> None:
        email = developer(ready, unique)
        _, token = a_token(ready, unique, email=email)
        ready.flush()

        revoke_role(ready, email=email, role_name=catalog.DEVELOPER, actor=ACTOR)
        ready.flush()

        assert authenticate(ready, token).permissions == frozenset()


class TestLastUsed:
    def test_is_written_once_and_not_again_within_the_minute(
        self, ready: Session, unique: str
    ) -> None:
        """A write per request would put a row update in front of every search."""
        row, _ = a_token(ready, unique)
        ready.flush()

        assert touch(ready, row) is True
        first = row.last_used_at
        assert first is not None

        assert touch(ready, row) is False
        assert row.last_used_at == first

    def test_is_written_again_once_the_window_has_passed(self, ready: Session, unique: str) -> None:
        row, _ = a_token(ready, unique)
        ready.flush()
        row.last_used_at = datetime.now(UTC) - timedelta(minutes=5)
        ready.flush()

        assert touch(ready, row) is True
        assert row.last_used_at is not None
        assert datetime.now(UTC) - row.last_used_at < timedelta(seconds=5)


class TestFindingAndListing:
    def test_a_prefix_nobody_has(self, ready: Session) -> None:
        with pytest.raises(TokenNotFound, match="dpol_zzzzzz"):
            find(ready, "dpol_zzzzzz")

    def test_a_prefix_that_matches_several_is_refused_rather_than_guessed(
        self, ready: Session, unique: str
    ) -> None:
        email = developer(ready, unique)
        a_token(ready, unique, email=email, name="one")
        a_token(ready, unique, email=email, name="two")
        ready.flush()

        with pytest.raises(AmbiguousPrefix, match="matches 2 tokens"):
            find(ready, "dpol_")

    def test_listing_by_owner(self, ready: Session, unique: str) -> None:
        mine = developer(ready, unique, "-mine")
        theirs = developer(ready, unique, "-theirs")
        a_token(ready, unique, email=mine, name="laptop")
        a_token(ready, unique, email=theirs, name="laptop")
        ready.flush()

        assert [row.owner.email for row in list_tokens(ready, email=mine)] == [mine]

    def test_status_reads_the_way_a_person_asks(self, ready: Session, unique: str) -> None:
        email = developer(ready, unique)
        row, _ = a_token(ready, unique, email=email)
        ready.flush()
        assert status_of(row) == "active"

        expired, _ = a_token(
            ready, unique, email=email, name="old", expires_at=datetime.now(UTC) - timedelta(days=1)
        )
        ready.flush()
        assert status_of(expired) == "expired"

        revoke(ready, prefix=row.prefix, actor=ACTOR)
        ready.flush()
        assert status_of(row) == "revoked"


class TestWhatTheLogSays:
    def test_creating_and_revoking_are_both_recorded(self, ready: Session, unique: str) -> None:
        before = len(read_entries(ready))
        row, _ = a_token(ready, unique)
        ready.flush()
        revoke(ready, prefix=row.prefix, actor=ACTOR)
        ready.flush()

        actions = [entry.action for entry in read_entries(ready)[before:]]
        assert PAT_CREATED in actions
        assert PAT_REVOKED in actions

    def test_the_entries_name_the_owner_by_id_and_never_by_address(
        self, ready: Session, unique: str
    ) -> None:
        email = developer(ready, unique)
        row, _ = a_token(ready, unique, email=email)
        ready.flush()

        entry = [
            found
            for found in read_entries(ready)
            if found.action == PAT_CREATED and found.target_id == str(row.id)
        ][-1]

        assert email not in entry.details_text
        assert str(row.user_id) in entry.details_text
        assert row.prefix in entry.details_text

    def test_revoking_twice_records_once(self, ready: Session, unique: str) -> None:
        row, _ = a_token(ready, unique)
        ready.flush()
        revoke(ready, prefix=row.prefix, actor=ACTOR)
        ready.flush()
        before = len(read_entries(ready))

        revoke(ready, prefix=row.prefix, actor=ACTOR)
        ready.flush()

        assert len(read_entries(ready)) == before


class TestTrustedSurface:
    def test_is_off_unless_asked_for(self, ready: Session, unique: str) -> None:
        row, _ = a_token(ready, unique)
        assert row.trusted_surface is False

    def test_can_be_set_for_a_service_account(self, ready: Session, unique: str) -> None:
        service = create_user(
            ready,
            email=f"mcp-{unique}@example.com",
            display_name="MCP server",
            actor=ACTOR,
            kind="service_account",
            roles=(catalog.DEVELOPER,),
        )
        ready.flush()

        row, _ = a_token(ready, unique, email=service.email, trusted_surface=True)
        ready.flush()

        assert row.trusted_surface is True
        assert ready.scalars(
            select(PersonalAccessToken.trusted_surface).where(PersonalAccessToken.id == row.id)
        ).one()


def test_the_governance_log_can_now_point_at_a_token(ready: Session, unique: str) -> None:
    """The column has been in the hash since the log existed. This is its table."""
    row, _ = a_token(ready, unique)
    ready.flush()

    seq = record(
        ready,
        actor=Actor(user_id=row.user_id, pat_id=row.id, via="api"),
        action="documents.published",
        target_type="document_version",
        target_id="testlaw:v1",
    )
    ready.flush()

    assert seq > 0


def test_an_invented_token_id_cannot_be_logged(ready: Session, unique: str) -> None:
    row, _ = a_token(ready, unique)
    ready.flush()
    invented = row.id

    # A Core insert reaches the database at once, so this is where it is refused.
    with pytest.raises(IntegrityError, match="actor_pat_id"):
        ready.execute(
            text(
                "INSERT INTO governance_log (occurred_at, actor_pat_id, action, target_type, "
                "target_id, details, prev_hash, entry_hash, hash_version) VALUES "
                "(now(), gen_random_uuid(), 'a', 't', '1', '{}'::json, '\\x00', '\\x01', 1)"
            )
        )
    ready.rollback()
    assert invented
