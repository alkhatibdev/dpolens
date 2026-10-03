"""The credential a surface reads from a file, and when it is replaced.

Two promises are under test. A restart does not invalidate the credential its
surfaces are already using, and a file that no longer holds a working credential
leads to exactly one that does, with the superseded one revoked rather than left
usable by whoever has a copy.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.models import PersonalAccessToken, User
from dpolens.engine.auth.surface import (
    SURFACE_EMAIL,
    SurfaceOwnerIsAPerson,
    ensure_surface,
)
from dpolens.engine.auth.tokens import OwnerCannotHoldTokens, authenticate, mint
from dpolens.engine.auth.users import create_user, deactivate
from dpolens.engine.logs.governance import PAT_CREATED, PAT_REVOKED, Actor, read_entries

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})


@pytest.fixture
def ready(session: Session) -> Session:
    bootstrap(session, actor=ACTOR)
    session.flush()
    return session


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """A path whose parent exists, which is the ordinary case."""
    return tmp_path / "surface-token"


def surface_email(unique: str) -> str:
    """One service account per test, since the table outlives each one."""
    return f"mcp-{unique}@surface.invalid"


def a_person(session: Session, unique: str) -> str:
    user = create_user(
        session,
        email=f"person-{unique}@example.com",
        display_name="A developer",
        actor=ACTOR,
        roles=(catalog.DEVELOPER,),
    )
    session.flush()
    return user.email


class TestFirstRun:
    def test_it_mints_writes_and_says_it_minted(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        done = ensure_surface(ready, path=path, actor=ACTOR, email=surface_email(unique))

        assert done.minted is True
        assert done.path == path
        written = path.read_text(encoding="utf-8").strip()
        assert written.startswith("dpol_")
        assert authenticate(ready, written).token.id == done.token.id

    def test_the_credential_may_delegate_and_may_do_nothing_else(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        """The whole of what a surface is trusted with, and the whole of what it is not."""
        done = ensure_surface(ready, path=path, actor=ACTOR, email=surface_email(unique))

        assert done.token.trusted_surface is True
        assert done.token.permissions == []
        who = authenticate(ready, path.read_text(encoding="utf-8").strip())
        assert who.permissions == frozenset()

    def test_only_its_owner_can_read_the_file(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        ensure_surface(ready, path=path, actor=ACTOR, email=surface_email(unique))

        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_it_creates_the_directory_it_was_given(
        self, ready: Session, tmp_path: Path, unique: str
    ) -> None:
        """A container mounts an empty volume, so the directory may not exist."""
        nested = tmp_path / "run" / "dpolens" / "surface-token"

        ensure_surface(ready, path=nested, actor=ACTOR, email=surface_email(unique))

        assert nested.read_text(encoding="utf-8").strip().startswith("dpol_")

    def test_it_leaves_nothing_half_written_behind(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        """The file is written beside itself and renamed, so a reader never sees half."""
        ensure_surface(ready, path=path, actor=ACTOR, email=surface_email(unique))

        assert sorted(entry.name for entry in path.parent.iterdir()) == [path.name]

    def test_the_owner_is_a_service_account_not_a_person(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        email = surface_email(unique)

        ensure_surface(ready, path=path, actor=ACTOR, email=email)

        owner = ready.scalars(select(User).where(User.email == email)).one()
        assert owner.kind == "service_account"
        assert owner.password_hash is None
        assert owner.roles == []

    def test_the_log_names_the_credential_by_id_and_not_the_address(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        before = len(read_entries(ready))

        done = ensure_surface(ready, path=path, actor=ACTOR, email=surface_email(unique))

        written = read_entries(ready)[before:]
        assert [entry.action for entry in written] == ["user.created", PAT_CREATED]
        assert str(done.token.id) in written[-1].target_id
        assert surface_email(unique) not in "".join(entry.details_text for entry in written)


class TestRunningItAgain:
    def test_a_working_credential_is_left_alone(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        email = surface_email(unique)
        first = ensure_surface(ready, path=path, actor=ACTOR, email=email)
        written = path.read_text(encoding="utf-8")
        before = len(read_entries(ready))

        again = ensure_surface(ready, path=path, actor=ACTOR, email=email)

        assert again.minted is False
        assert again.token.id == first.token.id
        assert path.read_text(encoding="utf-8") == written
        assert len(read_entries(ready)) == before

    def test_the_service_account_is_not_created_twice(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        email = surface_email(unique)
        ensure_surface(ready, path=path, actor=ACTOR, email=email)
        path.unlink()

        ensure_surface(ready, path=path, actor=ACTOR, email=email)

        assert len(ready.scalars(select(User).where(User.email == email)).all()) == 1

    def test_a_lost_file_supersedes_the_credential_it_held(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        """The secret cannot be recovered, so the row it belonged to is revoked.

        A volume that was wiped must not leave a credential usable by whoever
        copied it before the wipe.
        """
        email = surface_email(unique)
        first = ensure_surface(ready, path=path, actor=ACTOR, email=email)
        path.unlink()

        second = ensure_surface(ready, path=path, actor=ACTOR, email=email)

        assert second.minted is True
        assert second.token.id != first.token.id
        assert first.token.revoked_at is not None
        usable = [
            row
            for row in ready.scalars(
                select(PersonalAccessToken).where(
                    PersonalAccessToken.user_id == first.token.user_id
                )
            ).all()
            if row.revoked_at is None
        ]
        assert [row.id for row in usable] == [second.token.id]

    def test_superseding_is_recorded(self, ready: Session, path: Path, unique: str) -> None:
        email = surface_email(unique)
        ensure_surface(ready, path=path, actor=ACTOR, email=email)
        path.unlink()
        before = len(read_entries(ready))

        ensure_surface(ready, path=path, actor=ACTOR, email=email)

        assert [entry.action for entry in read_entries(ready)[before:]] == [
            PAT_REVOKED,
            PAT_CREATED,
        ]


class TestAFileThatCannotBeUsed:
    @pytest.mark.parametrize(
        "content",
        ["", "   \n", "not a token", "dpol_", "dpol_" + "a" * 43, "Bearer dpol_abc"],
        ids=["empty", "whitespace", "words", "scheme only", "right shape", "with the scheme word"],
    )
    def test_anything_that_does_not_authenticate_is_replaced(
        self, ready: Session, path: Path, unique: str, content: str
    ) -> None:
        path.write_text(content, encoding="utf-8")

        done = ensure_surface(ready, path=path, actor=ACTOR, email=surface_email(unique))

        assert done.minted is True
        assert (
            authenticate(ready, path.read_text(encoding="utf-8").strip()).token.id == done.token.id
        )

    def test_a_revoked_credential_is_replaced(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        email = surface_email(unique)
        first = ensure_surface(ready, path=path, actor=ACTOR, email=email)
        first.token.revoked_at = first.token.created_at
        ready.flush()

        second = ensure_surface(ready, path=path, actor=ACTOR, email=email)

        assert second.token.id != first.token.id
        assert path.read_text(encoding="utf-8").strip().startswith("dpol_")

    def test_a_persons_token_in_the_file_is_replaced_and_left_working(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        """A credential that works is not the same as a credential that may delegate.

        Somebody pasting their own token into the file gets a surface credential
        minted instead, and their token keeps working: it is not the instance's
        to revoke.
        """
        theirs, secret = mint(
            ready,
            email=a_person(ready, unique),
            name="laptop",
            permissions=(catalog.DOCUMENTS_READ,),
            actor=ACTOR,
        )
        path.write_text(secret, encoding="utf-8")

        done = ensure_surface(ready, path=path, actor=ACTOR, email=surface_email(unique))

        assert done.minted is True
        assert done.token.id != theirs.id
        assert theirs.revoked_at is None
        assert authenticate(ready, secret).token.id == theirs.id


class TestRefusals:
    def test_a_persons_address_is_refused_and_nothing_is_written(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        email = a_person(ready, unique)

        with pytest.raises(SurfaceOwnerIsAPerson, match="belongs to a person"):
            ensure_surface(ready, path=path, actor=ACTOR, email=email)

        assert not path.exists()

    def test_a_deactivated_service_account_is_refused(
        self, ready: Session, path: Path, unique: str
    ) -> None:
        """Deactivating the account is how an operator turns a surface off."""
        email = surface_email(unique)
        ensure_surface(ready, path=path, actor=ACTOR, email=email)
        path.unlink()
        deactivate(ready, email=email, actor=ACTOR)
        ready.flush()

        with pytest.raises(OwnerCannotHoldTokens, match="deactivated"):
            ensure_surface(ready, path=path, actor=ACTOR, email=email)

        assert not path.exists()


def test_the_default_address_is_an_address_that_cannot_receive_mail() -> None:
    """A service account must not look like a person in a list of users."""
    assert SURFACE_EMAIL.endswith(".invalid")
