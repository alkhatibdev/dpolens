"""The hash recipe, which is the whole value of the governance log.

These tests are the specification: if one of them has to change, the recipe
version has to change with it, because every export ever written was verified
against the behaviour asserted here.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from dpolens.engine.logs.governance import (
    HASH_VERSION,
    canonical_json,
    entry_hash,
    genesis_for,
    timestamp_text,
)

WHEN = datetime(2026, 9, 28, 10, 11, 12, 123456, tzinfo=UTC)
ACTOR = uuid.UUID("11111111-1111-1111-1111-111111111111")
PAT = uuid.UUID("22222222-2222-2222-2222-222222222222")

FIELDS: dict[str, Any] = {
    "prev_hash": b"\x00" * 32,
    "occurred_at": WHEN,
    "actor_user_id": ACTOR,
    "actor_pat_id": PAT,
    "action": "user.created",
    "target_type": "user",
    "target_id": "abc",
    "details_text": '{"email":"a@example.com","via":"cli"}',
}


def test_recipe_v1_has_a_fixed_value() -> None:
    """A known vector, so the recipe cannot drift without a test failing.

    Changing this value means every export already handed to an auditor verifies
    against a different rule, which is what `hash_version` exists to signal.
    """
    assert entry_hash(**FIELDS).hex() == (
        "daaf2e471819779c27502441f6e62b4a693c38e811e724a04031ffb6a7ed31ac"
    )


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_every_field_is_inside_the_hash(field: str) -> None:
    """No field can be edited without breaking the chain."""
    changed: dict[str, Any] = dict(FIELDS)
    if field == "prev_hash":
        changed[field] = b"\x01" * 32
    elif field == "occurred_at":
        changed[field] = WHEN + timedelta(microseconds=1)
    elif field in {"actor_user_id", "actor_pat_id"}:
        changed[field] = uuid.UUID("33333333-3333-3333-3333-333333333333")
    else:
        changed[field] = str(changed[field]) + "x"

    assert entry_hash(**changed) != entry_hash(**FIELDS)


def test_the_hash_version_is_inside_the_hash() -> None:
    assert entry_hash(**FIELDS, hash_version=2) != entry_hash(**FIELDS)


def test_field_boundaries_cannot_be_moved() -> None:
    """Why the fields are length-prefixed rather than concatenated.

    Without the prefixes, moving a character from one field to the next would
    leave the hash unchanged, so an entry about one target could be rewritten as
    one about another.
    """
    left = dict(FIELDS, target_type="user", target_id="abc")
    right = dict(FIELDS, target_type="use", target_id="rabc")

    assert entry_hash(**left) != entry_hash(**right)


def test_an_absent_actor_is_not_the_string_none() -> None:
    """A missing id is an empty field, so a CLI entry cannot be confused with a
    user whose id happens to serialise oddly."""
    without = dict(FIELDS, actor_user_id=None, actor_pat_id=None)
    literal_none = dict(FIELDS, actor_user_id=None, actor_pat_id=None, target_id="None")

    assert entry_hash(**without) != entry_hash(**literal_none)


class TestTimestampText:
    def test_always_six_fractional_digits(self) -> None:
        whole_second = datetime(2026, 9, 28, 10, 11, 12, 0, tzinfo=UTC)
        assert timestamp_text(whole_second) == "2026-09-28T10:11:12.000000Z"

    def test_converts_to_utc(self) -> None:
        gulf = timezone(timedelta(hours=4))
        assert timestamp_text(WHEN.astimezone(gulf)) == timestamp_text(WHEN)

    def test_microseconds_survive(self) -> None:
        assert timestamp_text(WHEN).endswith(".123456Z")


class TestCanonicalJson:
    def test_has_no_whitespace(self) -> None:
        assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'

    def test_keeps_document_order(self) -> None:
        """Keys are not sorted: the order the code wrote them is the order stored."""
        assert canonical_json({"b": 1, "a": 2}) == '{"b":1,"a":2}'

    def test_keeps_non_ascii_unescaped(self) -> None:
        assert canonical_json({"name": "حماد"}) == '{"name":"حماد"}'

    def test_refuses_values_json_cannot_round_trip(self) -> None:
        with pytest.raises(ValueError):
            canonical_json({"score": math.nan})

    @pytest.mark.parametrize(
        "details",
        [
            {"email": "a@example.com", "via": "cli"},
            {"permissions": ["documents.read", "queries.read_own"]},
            {"before": [], "after": ["roles.manage"], "nested": {"b": 1, "a": 2}},
            {"name": "حماد", "count": 3, "ok": True, "missing": None},
        ],
    )
    def test_round_trips_through_json(self, details: dict[str, object]) -> None:
        """The rule an export depends on.

        An exported entry carries `details` as an object so a person can read it,
        and a verifier re-serialises it to recompute the hash. That only works if
        parsing and re-serialising is the identity.
        """
        text = canonical_json(details)
        assert canonical_json(json.loads(text)) == text


def test_genesis_differs_between_instances() -> None:
    """So one instance's chain cannot be presented as another's."""
    assert genesis_for(ACTOR) != genesis_for(PAT)
    assert len(genesis_for(ACTOR)) == 32


def test_the_recipe_version_is_one() -> None:
    assert HASH_VERSION == 1
