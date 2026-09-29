"""The auditor's export: three files, verifiable without DPOLens.

`entries.jsonl` is the chain, one entry per line. `manifest.json` says what the
range is and whether it reaches the first entry ever written. `actors.json` maps
the ids in the chain to the people they were, and is the only file holding
personal data, which is why it is separate: the part an auditor verifies carries
none, so it survives an erasure request.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpolens import __version__
from dpolens.engine.auth.models import User
from dpolens.engine.instance import instance_id
from dpolens.engine.logs.governance import (
    DETAILS_SERIALISATION,
    EXPORT_FORMAT,
    GOVERNANCE_EXPORTED,
    HASH_VERSION,
    Actor,
    EntryRow,
    VerifyReport,
    canonical_json,
    genesis_for,
    read_entries,
    record,
    timestamp_text,
    verify_rows,
)

ENTRIES_FILE = "entries.jsonl"
MANIFEST_FILE = "manifest.json"
ACTORS_FILE = "actors.json"


class ExportRefused(Exception):
    """The export cannot be written where it was asked to go."""


class MalformedExport(Exception):
    """The files do not look like a governance export this build can read."""


def export(
    session: Session,
    directory: Path,
    *,
    actor: Actor,
    from_seq: int | None = None,
    to_seq: int | None = None,
) -> VerifyReport:
    """Write an export, and return the verification of what was written.

    The entry recording the export is appended after the rows are read, so an
    export never contains its own entry and two exports of the same range are
    byte-identical apart from the manifest's timestamp.
    """
    if directory.exists() and any(directory.iterdir()):
        raise ExportRefused(
            f"{directory} is not empty. An export writes three files and will not "
            "overwrite what is already there; give it a new directory."
        )
    directory.mkdir(parents=True, exist_ok=True)

    rows = read_entries(session, from_seq=from_seq, to_seq=to_seq)
    identifier = instance_id(session)
    genesis = genesis_for(identifier)
    anchored = bool(rows) and rows[0].prev_hash == genesis

    with (directory / ENTRIES_FILE).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_line(row), ensure_ascii=False) + "\n")

    manifest = {
        "format": EXPORT_FORMAT,
        "dpolens_version": __version__,
        "instance_id": str(identifier),
        "exported_at": timestamp_text(datetime.now(UTC)),
        "hash_version": HASH_VERSION,
        "details_serialisation": DETAILS_SERIALISATION,
        "entries": len(rows),
        "from_seq": rows[0].seq if rows else None,
        "to_seq": rows[-1].seq if rows else None,
        "genesis_hash": genesis.hex(),
        "anchored_to_genesis": anchored,
        "first_prev_hash": rows[0].prev_hash.hex() if rows else None,
        "final_entry_hash": rows[-1].entry_hash.hex() if rows else None,
    }
    (directory / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / ACTORS_FILE).write_text(
        json.dumps(_actors(session, rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    record(
        session,
        actor=actor,
        action=GOVERNANCE_EXPORTED,
        target_type="governance_log",
        target_id=f"{manifest['from_seq']}-{manifest['to_seq']}",
        details={
            "entries": len(rows),
            "from_seq": manifest["from_seq"],
            "to_seq": manifest["to_seq"],
            "anchored_to_genesis": anchored,
        },
    )
    return verify_export(directory)


def _line(row: EntryRow) -> dict[str, Any]:
    """One exported entry.

    `details` is written as an object rather than as escaped text, so the file
    can be read by a person. The manifest states how it is serialised for the
    hash, which is the same compact form the database holds.
    """
    return {
        "seq": row.seq,
        "occurred_at": timestamp_text(row.occurred_at),
        "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
        "actor_pat_id": str(row.actor_pat_id) if row.actor_pat_id else None,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "details": json.loads(row.details_text),
        "prev_hash": row.prev_hash.hex(),
        "entry_hash": row.entry_hash.hex(),
        "hash_version": row.hash_version,
    }


def _actors(session: Session, rows: list[EntryRow]) -> dict[str, dict[str, str]]:
    """Every user the chain mentions, whether they acted or were acted upon.

    The entries hold ids, so without this file an id cannot be turned into a
    person. Targets are included as well as actors, because "who was deactivated"
    is exactly the question an auditor asks.
    """
    ids: set[uuid.UUID] = {row.actor_user_id for row in rows if row.actor_user_id is not None}
    for row in rows:
        if row.target_type == "user":
            try:
                ids.add(uuid.UUID(row.target_id))
            except ValueError:
                continue
    if not ids:
        return {}
    users = session.scalars(select(User).where(User.id.in_(ids))).all()
    return {
        str(user.id): {
            "email": user.email,
            "display_name": user.display_name,
            "kind": user.kind,
            "status": user.status,
        }
        for user in sorted(users, key=lambda user: user.email)
    }


def verify_export(directory: Path) -> VerifyReport:
    """Verify an export from its files alone, trusting nothing else."""
    manifest_path = directory / MANIFEST_FILE
    entries_path = directory / ENTRIES_FILE
    for path in (manifest_path, entries_path):
        if not path.is_file():
            raise MalformedExport(f"{path} is missing, so this is not a governance export")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != EXPORT_FORMAT:
        raise MalformedExport(
            f"unknown export format {manifest.get('format')!r}, expected {EXPORT_FORMAT!r}"
        )

    rows = [
        _row(json.loads(line))
        for line in entries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if len(rows) != manifest.get("entries"):
        return VerifyReport(
            len(rows),
            rows[0].seq if rows else None,
            f"the manifest declares {manifest.get('entries')} entries and the file holds "
            f"{len(rows)}",
            anchored_to_genesis=bool(manifest.get("anchored_to_genesis")),
        )

    anchored = bool(manifest.get("anchored_to_genesis"))
    expected = manifest.get("genesis_hash") if anchored else manifest.get("first_prev_hash")
    if rows and not expected:
        raise MalformedExport("the manifest names no hash for the chain to start from")

    report = verify_rows(
        rows,
        expected_first_prev=bytes.fromhex(expected) if expected else b"",
        anchored=anchored,
    )
    if report.ok and rows and manifest.get("final_entry_hash") != rows[-1].entry_hash.hex():
        return VerifyReport(
            len(rows),
            rows[-1].seq,
            "the manifest's final hash is not the last entry's hash",
            anchored_to_genesis=anchored,
        )
    return report


def _row(line: dict[str, Any]) -> EntryRow:
    return EntryRow(
        seq=int(line["seq"]),
        occurred_at=datetime.strptime(line["occurred_at"], "%Y-%m-%dT%H:%M:%S.%f%z"),
        actor_user_id=uuid.UUID(line["actor_user_id"]) if line["actor_user_id"] else None,
        actor_pat_id=uuid.UUID(line["actor_pat_id"]) if line["actor_pat_id"] else None,
        action=line["action"],
        target_type=line["target_type"],
        target_id=line["target_id"],
        details_text=canonical_json(line["details"]),
        prev_hash=bytes.fromhex(line["prev_hash"]),
        entry_hash=bytes.fromhex(line["entry_hash"]),
        hash_version=int(line["hash_version"]),
    )
