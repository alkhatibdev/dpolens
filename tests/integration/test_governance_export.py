"""The export an auditor is handed, produced from a real chain.

The file tests in `tests/unit/test_export_verification.py` cover the ways an
export can be wrong. These cover what the instance actually writes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.users import create_user
from dpolens.engine.instance import instance_id
from dpolens.engine.logs.export import (
    ACTORS_FILE,
    ENTRIES_FILE,
    MANIFEST_FILE,
    ExportRefused,
    export,
    verify_export,
)
from dpolens.engine.logs.governance import (
    GOVERNANCE_EXPORTED,
    Actor,
    genesis_hash,
    read_entries,
    record,
)

pytestmark = pytest.mark.integration

ACTOR = Actor(via="cli", identity={"os_user": "tests", "host": "ci"})


@pytest.fixture
def ready(session: Session) -> Session:
    bootstrap(session, actor=ACTOR)
    session.flush()
    return session


def manifest_of(directory: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
    return loaded


def test_an_export_verifies_and_names_this_instance(ready: Session, tmp_path: Path) -> None:
    out = tmp_path / "export"
    report = export(ready, out, actor=ACTOR)

    assert report.ok
    assert report.anchored_to_genesis
    manifest = manifest_of(out)
    assert manifest["instance_id"] == str(instance_id(ready))
    assert manifest["genesis_hash"] == genesis_hash(ready).hex()
    assert manifest["entries"] == report.entries
    for name in (ENTRIES_FILE, MANIFEST_FILE, ACTORS_FILE):
        assert (out / name).is_file()


def test_the_entry_recording_an_export_is_not_inside_it(ready: Session, tmp_path: Path) -> None:
    """Otherwise no export could ever describe itself honestly."""
    out = tmp_path / "export"
    export(ready, out, actor=ACTOR)
    ready.flush()

    exported = [json.loads(line) for line in (out / ENTRIES_FILE).read_text().splitlines()]
    numbers = [line["seq"] for line in exported]

    last = read_entries(ready)[-1]
    assert last.action == GOVERNANCE_EXPORTED
    assert last.seq not in numbers
    assert last.seq > max(numbers)


def test_identities_live_in_their_own_file(ready: Session, tmp_path: Path, unique: str) -> None:
    """The part an auditor verifies carries no personal data at all.

    That is what lets the chain file survive an erasure request, and be handed
    over on its own.
    """
    user = create_user(ready, email=f"dpo-{unique}@example.com", display_name="A DPO", actor=ACTOR)
    ready.flush()
    record(
        ready,
        actor=Actor(user_id=user.id, via="api"),
        action="documents.published",
        target_type="document_version",
        target_id="testlaw:v1",
    )
    ready.flush()

    out = tmp_path / "export"
    assert export(ready, out, actor=ACTOR).ok

    entries = (out / ENTRIES_FILE).read_text(encoding="utf-8")
    assert "@example.com" not in entries, "the chain file must hold ids, never addresses"
    assert str(user.id) in entries

    actors = json.loads((out / ACTORS_FILE).read_text(encoding="utf-8"))
    assert actors[str(user.id)]["email"] == user.email
    assert actors[str(user.id)]["kind"] == "person"
    assert actors[str(user.id)]["display_name"] == "A DPO"


def test_a_user_who_was_only_a_target_is_still_named(
    ready: Session, tmp_path: Path, unique: str
) -> None:
    """The person a change was made to, not by, has to be identifiable too."""
    admin = create_user(
        ready,
        email=f"admin-{unique}@example.com",
        display_name="Admin",
        actor=ACTOR,
        roles=("Admin",),
    )
    target = create_user(
        ready, email=f"target-{unique}@example.com", display_name="Target", actor=ACTOR
    )
    ready.flush()

    out = tmp_path / "export"
    assert export(ready, out, actor=Actor(user_id=admin.id, via="api")).ok

    actors = json.loads((out / ACTORS_FILE).read_text(encoding="utf-8"))
    assert actors[str(target.id)]["email"] == target.email


def test_a_range_says_it_does_not_reach_the_beginning(ready: Session, tmp_path: Path) -> None:
    for number in range(4):
        record(ready, actor=ACTOR, action="a", target_type="t", target_id=str(number))
    ready.flush()
    rows = read_entries(ready)

    out = tmp_path / "range"
    report = export(ready, out, actor=ACTOR, from_seq=rows[-2].seq)

    assert report.ok
    assert not report.anchored_to_genesis
    assert manifest_of(out)["anchored_to_genesis"] is False
    assert verify_export(out).ok is True
    assert verify_export(out).anchored_to_genesis is False


def test_an_export_refuses_to_write_over_one_that_is_there(ready: Session, tmp_path: Path) -> None:
    """Evidence is not overwritten in place, even by accident."""
    out = tmp_path / "export"
    export(ready, out, actor=ACTOR)
    ready.flush()

    with pytest.raises(ExportRefused, match="not empty"):
        export(ready, out, actor=ACTOR)


def test_an_export_of_an_edited_file_stops_verifying(ready: Session, tmp_path: Path) -> None:
    """The same check an auditor runs, on the file they were given."""
    record(ready, actor=ACTOR, action="a", target_type="t", target_id="1")
    ready.flush()
    out = tmp_path / "export"
    assert export(ready, out, actor=ACTOR).ok

    lines = (out / ENTRIES_FILE).read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["target_id"] = "somebody-else"
    lines[0] = json.dumps(first)
    (out / ENTRIES_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify_export(out)
    assert not report.ok
    assert report.first_broken_seq == first["seq"]
