"""The catalog and the seeded roles, which are promises rather than defaults."""

from __future__ import annotations

import pytest

from dpolens.engine.auth import permissions as catalog


def test_the_catalog_holds_eleven_permissions() -> None:
    """A count, so adding one is a deliberate edit to this test as well."""
    assert len(catalog.PERMISSIONS) == 11


@pytest.mark.parametrize("key", sorted(catalog.PERMISSIONS))
def test_every_permission_is_area_then_action(key: str) -> None:
    area, _, action = key.partition(".")
    assert area and action, f"{key} is not in the form area.action"
    assert key.islower()


@pytest.mark.parametrize("key", sorted(catalog.PERMISSIONS))
def test_every_permission_says_what_it_allows(key: str) -> None:
    """The description reaches a dashboard, so an empty one is a bug."""
    assert catalog.PERMISSIONS[key].strip()


@pytest.mark.parametrize("role", sorted(catalog.SEEDED_ROLES))
def test_seeded_roles_only_use_real_permissions(role: str) -> None:
    """A typo here would seed a role that cannot be created at all."""
    assert catalog.SEEDED_ROLES[role] <= set(catalog.PERMISSIONS)


@pytest.mark.parametrize("role", sorted(catalog.SEEDED_ROLES))
def test_every_seeded_role_is_described(role: str) -> None:
    assert catalog.SEEDED_ROLE_DESCRIPTIONS[role].strip()


def test_admin_holds_everything() -> None:
    assert catalog.SEEDED_ROLES[catalog.ADMIN] == set(catalog.PERMISSIONS)


def test_no_seeded_role_can_see_who_asked() -> None:
    """The promise this project makes to developers, asserted rather than described.

    Seeing who asked a logged question is the surveillance switch. It starts off
    on every seeded role, so its first use is a grant somebody decided on, and
    that grant is itself a governance entry.
    """
    for role, held in catalog.SEEDED_ROLES.items():
        if role == catalog.ADMIN:
            continue
        assert catalog.QUERIES_READ_IDENTITIES not in held


def test_admin_is_the_only_seeded_role_that_manages_roles() -> None:
    """Which is what makes the lockout guard's question answerable."""
    managers = {role for role, held in catalog.SEEDED_ROLES.items() if catalog.ROLES_MANAGE in held}
    assert managers == {catalog.ADMIN}


def test_the_developer_can_read_the_corpus_and_mint_a_token() -> None:
    """The hero flow needs exactly these two things and nothing else."""
    assert catalog.SEEDED_ROLES[catalog.DEVELOPER] == {
        catalog.DOCUMENTS_READ,
        catalog.QUERIES_READ_OWN,
        catalog.TOKENS_CREATE,
    }


def test_the_dpo_reads_every_question_but_not_who_asked() -> None:
    held = catalog.SEEDED_ROLES[catalog.DPO]
    assert catalog.QUERIES_READ_ALL in held
    assert catalog.GOVERNANCE_READ in held
    assert catalog.QUERIES_READ_IDENTITIES not in held
    assert catalog.USERS_MANAGE not in held


def test_the_catalog_cannot_be_edited_at_runtime() -> None:
    """Code is the source of truth, so the mapping is not a mutable dict."""
    with pytest.raises(TypeError):
        catalog.PERMISSIONS["documents.delete"] = "no"  # type: ignore[index]
