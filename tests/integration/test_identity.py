"""Users, roles and the rules that stop an instance locking everyone out.

The interesting cases are all refusals: the second user with the same address,
the last administrator being demoted, a role deleted while somebody holds it.
Those are what an access control system is for.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.catalog import StalePermission, bootstrap, sync_catalog
from dpolens.engine.auth.models import Permission, Role, User
from dpolens.engine.auth.roles import (
    DuplicateRole,
    RoleInUse,
    UnknownPermission,
    create_role,
    delete_role,
    grant_permission,
    revoke_permission,
)
from dpolens.engine.auth.users import (
    DuplicateEmail,
    LockoutRefused,
    RoleNotFound,
    UserNotFound,
    activate,
    create_user,
    deactivate,
    get_user,
    grant_role,
    managers,
    revoke_role,
)
from dpolens.engine.logs.governance import ROLE_SEEDED, Actor, record
from dpolens.engine.logs.models import GovernanceEntry

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})


@pytest.fixture
def ready(session: Session) -> Session:
    """A database with the catalog synced and the three roles seeded."""
    bootstrap(session, actor=ACTOR)
    session.flush()
    return session


def admin(session: Session, unique: str, suffix: str = "") -> User:
    return create_user(
        session,
        email=f"admin{suffix}-{unique}@example.com",
        display_name="An administrator",
        actor=ACTOR,
        roles=(catalog.ADMIN,),
    )


class TestBootstrap:
    def test_seeds_the_catalog_and_the_three_roles(self, ready: Session) -> None:
        keys = set(ready.scalars(select(Permission.key)).all())
        assert keys == set(catalog.PERMISSIONS)

        for name, expected in catalog.SEEDED_ROLES.items():
            role = ready.scalars(select(Role).where(Role.name == name)).one()
            assert role.permission_keys() == expected
            assert role.is_seeded

    def test_running_twice_changes_nothing(self, ready: Session) -> None:
        """Every surface runs this at startup, so it has to be idempotent."""
        before = ready.scalar(select(func.count()).select_from(Role))
        seeded_before = ready.scalar(
            select(func.count())
            .select_from(GovernanceEntry)
            .where(GovernanceEntry.action == ROLE_SEEDED)
        )

        created = bootstrap(ready, actor=ACTOR)
        ready.flush()

        assert created == []
        assert ready.scalar(select(func.count()).select_from(Role)) == before
        assert (
            ready.scalar(
                select(func.count())
                .select_from(GovernanceEntry)
                .where(GovernanceEntry.action == ROLE_SEEDED)
            )
            == seeded_before
        )

    def test_a_deleted_seeded_role_does_not_come_back(self, ready: Session) -> None:
        """Deleting Developer is a decision, and a later start must not undo it.

        Whether a role has been seeded is read from the governance log rather
        than from the roles table, because the log is the one record that cannot
        be quietly removed.
        """
        delete_role(ready, role_name=catalog.DEVELOPER, actor=ACTOR)
        ready.flush()

        assert bootstrap(ready, actor=ACTOR) == []
        assert ready.scalars(select(Role).where(Role.name == catalog.DEVELOPER)).first() is None


class TestCatalogSync:
    def test_a_permission_dropped_from_code_but_still_held_stops_the_instance(
        self, ready: Session, unique: str
    ) -> None:
        """The refusal names the role and the key, because that is what has to change."""
        ready.add(Permission(key="documents.delete", description="left over from a future build"))
        ready.flush()
        role = create_role(ready, name=f"Archivist-{unique}", actor=ACTOR)
        role.permissions.append(ready.get_one(Permission, "documents.delete"))
        ready.flush()

        with pytest.raises(StalePermission) as raised:
            sync_catalog(ready)

        assert "documents.delete" in str(raised.value)
        assert f"Archivist-{unique}" in str(raised.value)

    def test_a_permission_nobody_holds_is_removed(self, ready: Session) -> None:
        ready.add(Permission(key="documents.delete", description="left over"))
        ready.flush()

        sync_catalog(ready)
        ready.flush()

        assert ready.get(Permission, "documents.delete") is None

    def test_a_description_edited_in_the_database_is_restored(self, ready: Session) -> None:
        """Code is the source of truth, including for the words in a dashboard."""
        row = ready.get_one(Permission, catalog.DOCUMENTS_READ)
        row.description = "something somebody typed into psql"
        ready.flush()

        sync_catalog(ready)
        ready.flush()

        assert (
            ready.get_one(Permission, catalog.DOCUMENTS_READ).description
            == (catalog.PERMISSIONS[catalog.DOCUMENTS_READ])
        )


class TestCreatingUsers:
    def test_an_address_is_stored_lowercased(self, ready: Session, unique: str) -> None:
        user = create_user(
            ready,
            email=f"  MiXeD-{unique}@Example.COM ",
            display_name="Mixed case",
            actor=ACTOR,
        )
        assert user.email == f"mixed-{unique}@example.com"
        assert get_user(ready, f"MIXED-{unique}@EXAMPLE.COM").id == user.id

    def test_the_same_address_in_another_case_is_a_duplicate(
        self, ready: Session, unique: str
    ) -> None:
        create_user(ready, email=f"dpo-{unique}@example.com", display_name="First", actor=ACTOR)
        with pytest.raises(DuplicateEmail):
            create_user(
                ready, email=f"DPO-{unique}@EXAMPLE.COM", display_name="Second", actor=ACTOR
            )

    def test_a_role_that_does_not_exist_is_refused(self, ready: Session, unique: str) -> None:
        with pytest.raises(RoleNotFound, match="Auditor"):
            create_user(
                ready,
                email=f"nobody-{unique}@example.com",
                display_name="Nobody",
                actor=ACTOR,
                roles=("Auditor",),
            )

    def test_an_unknown_address_is_named_in_the_error(self, ready: Session) -> None:
        with pytest.raises(UserNotFound, match=r"ghost@example\.com"):
            get_user(ready, "ghost@example.com")

    def test_a_service_account_has_no_password_and_cannot_hold_the_instance_open(
        self, ready: Session, unique: str
    ) -> None:
        """A service account may hold Admin and still not satisfy the guard."""
        robot = create_user(
            ready,
            email=f"ci-{unique}@example.com",
            display_name="CI",
            actor=ACTOR,
            kind="service_account",
            roles=(catalog.ADMIN,),
        )
        person = admin(ready, unique)
        ready.flush()

        assert robot.password_hash is None
        assert robot not in managers(ready)

        with pytest.raises(LockoutRefused):
            deactivate(ready, email=person.email, actor=ACTOR)
        ready.rollback()


class TestEffectivePermissions:
    def test_a_users_permissions_are_the_union_of_their_roles(
        self, ready: Session, unique: str
    ) -> None:
        user = create_user(
            ready,
            email=f"both-{unique}@example.com",
            display_name="Two hats",
            actor=ACTOR,
            roles=(catalog.DEVELOPER, catalog.DPO),
        )
        ready.flush()

        assert user.effective_permissions() == (
            catalog.SEEDED_ROLES[catalog.DEVELOPER] | catalog.SEEDED_ROLES[catalog.DPO]
        )

    def test_a_deactivated_user_holds_nothing_and_keeps_their_roles(
        self, ready: Session, unique: str
    ) -> None:
        """Deactivation blocks access; it does not throw away what to restore."""
        admin(ready, unique, "-keeper")
        user = create_user(
            ready,
            email=f"leaver-{unique}@example.com",
            display_name="Leaver",
            actor=ACTOR,
            roles=(catalog.DPO,),
        )
        ready.flush()

        deactivate(ready, email=user.email, actor=ACTOR)
        ready.flush()
        assert user.effective_permissions() == frozenset()
        assert [role.name for role in user.roles] == [catalog.DPO]

        activate(ready, email=user.email, actor=ACTOR)
        ready.flush()
        assert user.effective_permissions() == catalog.SEEDED_ROLES[catalog.DPO]
        assert user.deactivated_at is None

    def test_granting_the_same_role_twice_is_not_an_error(
        self, ready: Session, unique: str
    ) -> None:
        user = create_user(
            ready,
            email=f"twice-{unique}@example.com",
            display_name="Twice",
            actor=ACTOR,
            roles=(catalog.DEVELOPER,),
        )
        grant_role(ready, email=user.email, role_name=catalog.DEVELOPER, actor=ACTOR)
        ready.flush()

        assert [role.name for role in user.roles] == [catalog.DEVELOPER]


class TestLockoutGuard:
    def test_the_last_administrator_cannot_be_demoted(self, ready: Session, unique: str) -> None:
        person = admin(ready, unique)
        ready.flush()

        with pytest.raises(LockoutRefused, match=catalog.ROLES_MANAGE):
            revoke_role(ready, email=person.email, role_name=catalog.ADMIN, actor=ACTOR)
        ready.rollback()

    def test_the_last_administrator_cannot_be_deactivated(
        self, ready: Session, unique: str
    ) -> None:
        person = admin(ready, unique)
        ready.flush()

        with pytest.raises(LockoutRefused):
            deactivate(ready, email=person.email, actor=ACTOR)
        ready.rollback()

    def test_the_permission_cannot_be_taken_from_the_role_that_carries_it(
        self, ready: Session, unique: str
    ) -> None:
        """The guard is about who holds the permission, not about a role's name."""
        admin(ready, unique)
        ready.flush()

        with pytest.raises(LockoutRefused):
            revoke_permission(
                ready,
                role_name=catalog.ADMIN,
                permission=catalog.ROLES_MANAGE,
                actor=ACTOR,
            )
        ready.rollback()

    def test_one_of_two_administrators_can_be_demoted(self, ready: Session, unique: str) -> None:
        first = admin(ready, unique, "-one")
        admin(ready, unique, "-two")
        ready.flush()

        revoke_role(ready, email=first.email, role_name=catalog.ADMIN, actor=ACTOR)
        ready.flush()

        assert first.roles == []
        assert len(managers(ready)) == 1

    def test_another_role_carrying_the_permission_satisfies_the_guard(
        self, ready: Session, unique: str
    ) -> None:
        """Nothing privileges the seeded Admin role: the permission is what counts."""
        owner = create_role(
            ready,
            name=f"Owner-{unique}",
            actor=ACTOR,
            permissions=(catalog.ROLES_MANAGE,),
        )
        person = admin(ready, unique)
        create_user(
            ready,
            email=f"owner-{unique}@example.com",
            display_name="Owner",
            actor=ACTOR,
            roles=(owner.name,),
        )
        ready.flush()

        revoke_role(ready, email=person.email, role_name=catalog.ADMIN, actor=ACTOR)
        ready.flush()

        assert [user.email for user in managers(ready)] == [f"owner-{unique}@example.com"]


class TestRoles:
    def test_two_roles_cannot_share_a_name(self, ready: Session, unique: str) -> None:
        create_role(ready, name=f"Legal-{unique}", actor=ACTOR)
        with pytest.raises(DuplicateRole):
            create_role(ready, name=f"Legal-{unique}", actor=ACTOR)

    def test_a_permission_outside_the_catalog_is_refused(self, ready: Session, unique: str) -> None:
        """The catalog is listed in the message, because that is the next question."""
        with pytest.raises(UnknownPermission) as raised:
            create_role(
                ready, name=f"Wrong-{unique}", actor=ACTOR, permissions=("documents.destroy",)
            )
        assert catalog.DOCUMENTS_READ in str(raised.value)

    def test_granting_an_unknown_permission_is_refused(self, ready: Session) -> None:
        with pytest.raises(UnknownPermission):
            grant_permission(
                ready, role_name=catalog.DPO, permission="documents.destroy", actor=ACTOR
            )

    def test_revoking_a_permission_a_role_never_had_is_a_no_op(self, ready: Session) -> None:
        role = revoke_permission(
            ready,
            role_name=catalog.DEVELOPER,
            permission=catalog.QUERIES_READ_IDENTITIES,
            actor=ACTOR,
        )
        assert role.permission_keys() == catalog.SEEDED_ROLES[catalog.DEVELOPER]

    def test_a_role_somebody_holds_cannot_be_deleted(self, ready: Session, unique: str) -> None:
        person = admin(ready, unique)
        ready.flush()

        with pytest.raises(RoleInUse, match=re.escape(person.email)):
            delete_role(ready, role_name=catalog.ADMIN, actor=ACTOR)
        ready.rollback()

    def test_a_role_nobody_holds_can_be_deleted(self, ready: Session, unique: str) -> None:
        create_role(ready, name=f"Temporary-{unique}", actor=ACTOR)
        ready.flush()

        delete_role(ready, role_name=f"Temporary-{unique}", actor=ACTOR)
        ready.flush()

        assert ready.scalars(select(Role).where(Role.name == f"Temporary-{unique}")).first() is None


def test_a_user_the_log_points_at_cannot_be_deleted(ready: Session, unique: str) -> None:
    """Why deactivation exists: attribution has to survive somebody leaving."""
    user = create_user(
        ready, email=f"logged-{unique}@example.com", display_name="Logged", actor=ACTOR
    )
    ready.flush()
    record(
        ready,
        actor=Actor(user_id=user.id, via="api"),
        action="documents.published",
        target_type="document_version",
        target_id="testlaw:v1",
    )
    ready.flush()

    ready.delete(user)
    with pytest.raises(IntegrityError):
        ready.flush()
    ready.rollback()
