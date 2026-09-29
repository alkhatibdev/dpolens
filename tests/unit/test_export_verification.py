"""Verifying a chain and an export, with no database in the way.

Every test here is a way the evidence could be wrong: a rewritten field, a
removed entry, a manifest that disagrees with the file it describes.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dpolens.engine.logs.export import (
    ACTORS_FILE,
    ENTRIES_FILE,
    MANIFEST_FILE,
    MalformedExport,
    verify_export,
)
from dpolens.engine.logs.governance import (
    EXPORT_FORMAT,
    HASH_VERSION,
    EntryRow,
    canonical_json,
    entry_hash,
    genesis_for,
    timestamp_text,
    verify_rows,
)

INSTANCE = uuid.UUID("44444444-4444-4444-4444-444444444444")
GENESIS = genesis_for(INSTANCE)
START = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)


def make_row(
    seq: int, prev_hash: bytes, *, action: str = "user.created", **overrides: Any
) -> EntryRow:
    """One well-formed entry, hashed the way `record` would have hashed it."""
    fields: dict[str, Any] = {
        "seq": seq,
        "occurred_at": START + timedelta(seconds=seq),
        "actor_user_id": None,
        "actor_pat_id": None,
        "action": action,
        "target_type": "user",
        "target_id": f"target-{seq}",
        "details_text": canonical_json({"seq": seq, "via": "cli"}),
        "prev_hash": prev_hash,
        "hash_version": HASH_VERSION,
    }
    fields.update(overrides)
    digest = entry_hash(
        prev_hash=fields["prev_hash"],
        occurred_at=fields["occurred_at"],
        actor_user_id=fields["actor_user_id"],
        actor_pat_id=fields["actor_pat_id"],
        action=fields["action"],
        target_type=fields["target_type"],
        target_id=fields["target_id"],
        details_text=fields["details_text"],
        hash_version=fields["hash_version"],
    )
    return EntryRow(**fields, entry_hash=digest)


def chain(length: int, *, first_prev: bytes = GENESIS) -> list[EntryRow]:
    rows: list[EntryRow] = []
    previous = first_prev
    for seq in range(1, length + 1):
        row = make_row(seq, previous)
        rows.append(row)
        previous = row.entry_hash
    return rows


class TestVerifyRows:
    def test_an_empty_chain_verifies(self) -> None:
        """A fresh instance has nothing to prove, and should not report a fault."""
        report = verify_rows([], expected_first_prev=GENESIS, anchored=True)
        assert report.ok
        assert report.entries == 0

    def test_a_well_formed_chain_verifies(self) -> None:
        report = verify_rows(chain(5), expected_first_prev=GENESIS, anchored=True)
        assert report.ok
        assert report.entries == 5

    def test_a_rewritten_field_is_caught_and_named(self) -> None:
        rows = chain(3)
        tampered = EntryRow(
            **{**rows[1].__dict__, "target_id": "somebody-else"},
        )
        rows[1] = tampered

        report = verify_rows(rows, expected_first_prev=GENESIS, anchored=True)
        assert not report.ok
        assert report.first_broken_seq == 2
        assert report.reason is not None
        assert "own hash" in report.reason

    def test_a_removed_entry_breaks_the_links(self) -> None:
        """The reason distinguishes a broken link from a rewritten field."""
        rows = chain(4)
        del rows[2]

        report = verify_rows(rows, expected_first_prev=GENESIS, anchored=True)
        assert not report.ok
        assert report.first_broken_seq == 4
        assert report.reason is not None
        assert "link" in report.reason

    def test_the_wrong_genesis_is_caught(self) -> None:
        """A chain from another instance does not verify here."""
        report = verify_rows(chain(2), expected_first_prev=genesis_for(uuid.uuid4()), anchored=True)
        assert not report.ok
        assert report.reason is not None
        assert "start" in report.reason

    def test_two_entries_claiming_the_same_predecessor(self) -> None:
        rows = chain(2)
        rows.append(make_row(3, rows[0].entry_hash, action="role.created"))

        report = verify_rows(rows, expected_first_prev=GENESIS, anchored=True)
        assert not report.ok
        assert report.reason is not None
        assert "same one" in report.reason

    def test_an_unknown_hash_version_is_refused_rather_than_guessed(self) -> None:
        rows = chain(1)
        rows.append(make_row(2, rows[0].entry_hash, hash_version=HASH_VERSION + 1))

        report = verify_rows(rows, expected_first_prev=GENESIS, anchored=True)
        assert not report.ok
        assert report.first_broken_seq == 2
        assert report.reason is not None
        assert "hash version" in report.reason

    def test_links_in_a_different_order_than_the_numbers(self) -> None:
        """Sequence numbers order the table; the links are what prove the order."""
        first = make_row(9, GENESIS)
        second = make_row(4, first.entry_hash)

        report = verify_rows([first, second], expected_first_prev=GENESIS, anchored=True)
        assert not report.ok
        assert report.out_of_order == (9, 4)

    def test_a_range_can_be_checked_without_its_beginning(self) -> None:
        rows = chain(5)[2:]
        report = verify_rows(rows, expected_first_prev=rows[0].prev_hash, anchored=False)
        assert report.ok
        assert not report.anchored_to_genesis


def write_export(directory: Path, rows: list[EntryRow], *, anchored: bool = True) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        {
            "seq": row.seq,
            "occurred_at": timestamp_text(row.occurred_at),
            "actor_user_id": None,
            "actor_pat_id": None,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "details": json.loads(row.details_text),
            "prev_hash": row.prev_hash.hex(),
            "entry_hash": row.entry_hash.hex(),
            "hash_version": row.hash_version,
        }
        for row in rows
    ]
    (directory / ENTRIES_FILE).write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    (directory / MANIFEST_FILE).write_text(
        json.dumps(
            {
                "format": EXPORT_FORMAT,
                "instance_id": str(INSTANCE),
                "hash_version": HASH_VERSION,
                "entries": len(rows),
                "from_seq": rows[0].seq if rows else None,
                "to_seq": rows[-1].seq if rows else None,
                "genesis_hash": GENESIS.hex(),
                "anchored_to_genesis": anchored,
                "first_prev_hash": rows[0].prev_hash.hex() if rows else None,
                "final_entry_hash": rows[-1].entry_hash.hex() if rows else None,
            }
        ),
        encoding="utf-8",
    )
    (directory / ACTORS_FILE).write_text("{}", encoding="utf-8")


class TestVerifyExport:
    def test_a_good_export_verifies_from_the_files_alone(self, tmp_path: Path) -> None:
        write_export(tmp_path, chain(3))
        assert verify_export(tmp_path).ok

    def test_a_missing_file_is_not_an_export(self, tmp_path: Path) -> None:
        write_export(tmp_path, chain(2))
        (tmp_path / MANIFEST_FILE).unlink()

        with pytest.raises(MalformedExport, match="missing"):
            verify_export(tmp_path)

    def test_an_unknown_format_is_refused(self, tmp_path: Path) -> None:
        """A future format is not guessed at, because the hash rules could differ."""
        write_export(tmp_path, chain(2))
        manifest = json.loads((tmp_path / MANIFEST_FILE).read_text(encoding="utf-8"))
        manifest["format"] = "something-else/9"
        (tmp_path / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")

        with pytest.raises(MalformedExport, match="unknown export format"):
            verify_export(tmp_path)

    def test_an_edited_entry_in_the_file_is_caught(self, tmp_path: Path) -> None:
        write_export(tmp_path, chain(3))
        lines = (tmp_path / ENTRIES_FILE).read_text(encoding="utf-8").splitlines()
        second = json.loads(lines[1])
        second["details"]["seq"] = 99
        lines[1] = json.dumps(second)
        (tmp_path / ENTRIES_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = verify_export(tmp_path)
        assert not report.ok
        assert report.first_broken_seq == 2

    def test_a_dropped_line_contradicts_the_manifest(self, tmp_path: Path) -> None:
        write_export(tmp_path, chain(3))
        lines = (tmp_path / ENTRIES_FILE).read_text(encoding="utf-8").splitlines()
        (tmp_path / ENTRIES_FILE).write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

        report = verify_export(tmp_path)
        assert not report.ok
        assert report.reason is not None
        assert "declares 3 entries" in report.reason

    def test_a_rewritten_final_hash_is_caught(self, tmp_path: Path) -> None:
        """The manifest is evidence too, so it is checked against the entries."""
        write_export(tmp_path, chain(3))
        manifest = json.loads((tmp_path / MANIFEST_FILE).read_text(encoding="utf-8"))
        manifest["final_entry_hash"] = "00" * 32
        (tmp_path / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")

        report = verify_export(tmp_path)
        assert not report.ok
        assert report.reason is not None
        assert "final hash" in report.reason

    def test_a_range_says_it_does_not_reach_genesis(self, tmp_path: Path) -> None:
        write_export(tmp_path, chain(5)[2:], anchored=False)

        report = verify_export(tmp_path)
        assert report.ok
        assert not report.anchored_to_genesis

    def test_a_range_cannot_claim_to_be_anchored(self, tmp_path: Path) -> None:
        """Flipping the flag does not make the chain start at genesis."""
        write_export(tmp_path, chain(5)[2:], anchored=True)

        report = verify_export(tmp_path)
        assert not report.ok
