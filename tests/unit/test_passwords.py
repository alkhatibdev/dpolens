"""Passwords: a length rule, a slow hash, and nothing a timer could read."""

from __future__ import annotations

import pytest

from dpolens.engine.auth.passwords import (
    MAX_LENGTH,
    MIN_LENGTH,
    WeakPassword,
    hash_password,
    needs_rehash,
    rehash,
    verify,
)

GOOD = "correct horse battery staple"


def test_a_password_is_stored_as_an_argon2id_hash() -> None:
    stored = hash_password(GOOD)

    assert stored.startswith("$argon2id$")
    assert GOOD not in stored


def test_the_right_password_matches_and_any_other_does_not() -> None:
    stored = hash_password(GOOD)

    assert verify(stored, GOOD)
    assert not verify(stored, GOOD.upper())
    assert not verify(stored, "")


def test_length_is_the_only_rule() -> None:
    """NIST SP 800-63B: no composition rules, a minimum length."""
    with pytest.raises(WeakPassword, match=f"at least {MIN_LENGTH}"):
        hash_password("x" * (MIN_LENGTH - 1))
    with pytest.raises(WeakPassword, match=f"at most {MAX_LENGTH}"):
        hash_password("x" * (MAX_LENGTH + 1))

    assert verify(hash_password("aaaaaaaaaaaa"), "aaaaaaaaaaaa")


def test_an_account_without_a_password_never_matches() -> None:
    """Checked against a decoy, so the answer takes as long as a real one."""
    assert not verify(None, GOOD)
    assert not verify(None, "a password that belongs to nobody")


def test_a_hash_that_is_not_one_does_not_match() -> None:
    assert not verify("not a hash", GOOD)


def test_a_fresh_hash_needs_no_rehash_and_a_rehash_skips_the_length_rule() -> None:
    """A password set before a stricter rule is still the password."""
    assert not needs_rehash(hash_password(GOOD))
    assert verify(rehash("short"), "short")
