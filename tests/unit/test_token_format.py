"""The token's shape and the arithmetic of what it may do, with no database.

A token is the one secret this project asks anybody to hold, so its format and
the intersection rule are worth pinning down on their own.
"""

from __future__ import annotations

import hashlib

import pytest

from dpolens.engine.auth import permissions as catalog
from dpolens.engine.auth.models import Permission, Role, User
from dpolens.engine.auth.tokens import (
    PREFIX_LENGTH,
    SCHEME,
    digest_of,
    effective_permissions,
    generate,
    looks_like_a_token,
)


class FakeToken:
    """Just the permissions, because that is all the intersection reads."""

    def __init__(self, *permissions: str) -> None:
        self.permissions = list(permissions)


def role(name: str, *keys: str) -> Role:
    return Role(name=name, permissions=[Permission(key=key, description=key) for key in keys])


class TestGenerate:
    def test_carries_the_scheme_and_enough_entropy(self) -> None:
        token, _, _ = generate()
        assert token.startswith(SCHEME)
        # 32 random bytes in base64url, unpadded.
        assert len(token) - len(SCHEME) == 43

    def test_two_tokens_are_not_the_same(self) -> None:
        assert generate()[0] != generate()[0]

    def test_the_prefix_is_the_start_of_the_token_and_nothing_more(self) -> None:
        token, _, prefix = generate()
        assert token.startswith(prefix)
        assert len(prefix) == PREFIX_LENGTH
        assert len(prefix) < len(token)

    def test_what_is_stored_is_not_the_token(self) -> None:
        token, stored, _ = generate()
        assert stored == hashlib.sha256(token.encode()).hexdigest()
        assert token not in stored
        assert stored != token
        assert len(stored) == 64


class TestDigest:
    def test_one_character_changes_everything(self) -> None:
        token, stored, _ = generate()
        assert digest_of(token[:-1] + ("a" if token[-1] != "a" else "b")) != stored

    def test_is_stable(self) -> None:
        assert digest_of("dpol_example") == digest_of("dpol_example")


class TestShapeCheck:
    @pytest.mark.parametrize(
        "presented",
        [
            "",
            "Bearer something",
            SCHEME,
            "ghp_0123456789",
            "dpol-0123456789",
            " dpol_0123456789",
        ],
    )
    def test_refuses_what_cannot_be_ours(self, presented: str) -> None:
        """A header full of noise should cost no database query."""
        assert looks_like_a_token(presented) is False

    def test_accepts_a_real_one(self) -> None:
        assert looks_like_a_token(generate()[0]) is True


class TestEffectivePermissions:
    def test_is_the_intersection_with_what_the_owner_holds_now(self) -> None:
        owner = User(
            email="dev@example.com",
            display_name="Dev",
            status="active",
            roles=[role("Developer", *catalog.SEEDED_ROLES[catalog.DEVELOPER])],
        )
        token = FakeToken(catalog.DOCUMENTS_READ, catalog.QUERIES_READ_OWN)

        assert effective_permissions(token, owner) == {  # type: ignore[arg-type]
            catalog.DOCUMENTS_READ,
            catalog.QUERIES_READ_OWN,
        }

    def test_a_permission_the_owner_has_lost_is_gone_from_the_token(self) -> None:
        """Nothing rewrites the token: the intersection is computed per request."""
        owner = User(
            email="dev@example.com",
            display_name="Dev",
            status="active",
            roles=[role("Thin", catalog.DOCUMENTS_READ)],
        )
        token = FakeToken(catalog.DOCUMENTS_READ, catalog.QUERIES_READ_ALL)

        assert effective_permissions(token, owner) == {catalog.DOCUMENTS_READ}  # type: ignore[arg-type]

    def test_a_token_cannot_gain_from_a_later_grant_it_never_asked_for(self) -> None:
        owner = User(
            email="dpo@example.com",
            display_name="DPO",
            status="active",
            roles=[role("DPO", *catalog.SEEDED_ROLES[catalog.DPO])],
        )
        token = FakeToken(catalog.DOCUMENTS_READ)

        assert effective_permissions(token, owner) == {catalog.DOCUMENTS_READ}  # type: ignore[arg-type]

    def test_a_deactivated_owner_leaves_nothing(self) -> None:
        owner = User(
            email="gone@example.com",
            display_name="Gone",
            status="deactivated",
            roles=[role("Admin", *catalog.PERMISSIONS)],
        )
        token = FakeToken(catalog.DOCUMENTS_READ)

        assert effective_permissions(token, owner) == frozenset()  # type: ignore[arg-type]

    def test_a_user_whose_status_is_not_set_yet_holds_nothing(self) -> None:
        """The guard fails closed.

        A row's status is applied by the database on insert, so an object that has
        not been saved has none. Reading permissions from it has to give nothing
        rather than everything.
        """
        owner = User(
            email="new@example.com",
            display_name="Unsaved",
            roles=[role("Admin", *catalog.PERMISSIONS)],
        )

        assert owner.status is None
        token = FakeToken(catalog.DOCUMENTS_READ)
        assert effective_permissions(token, owner) == frozenset()
