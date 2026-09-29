"""Writing, verifying and exporting the governance log.

The hash recipe is written out here and in `docs/governance-log.md`, in enough
detail to be reimplemented in another language, because an export nobody else
can verify is not evidence of anything.

Recipe v1. For each entry, SHA-256 over the concatenation of these fields, in
this order, each prefixed by its length as eight bytes big-endian:

    1. the hash version, as decimal digits
    2. prev_hash, raw bytes
    3. occurred_at, UTC, "YYYY-MM-DDTHH:MM:SS.ffffffZ" with exactly six digits
    4. actor_user_id, or an empty field when there is none
    5. actor_pat_id, or an empty field when there is none
    6. action
    7. target_type
    8. target_id
    9. details, the exact JSON text that was stored

Length prefixes are what make the concatenation unambiguous, so no
canonicalisation standard has to be agreed on to verify a chain. The first
entry's prev_hash is SHA-256 of this instance's id, so one instance's chain
cannot be presented as another's.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import socket
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Text, cast, func, insert, literal, select
from sqlalchemy.orm import Session

from dpolens.engine.instance import instance_id
from dpolens.engine.logs.models import GovernanceEntry

HASH_VERSION = 1

EXPORT_FORMAT = "dpolens-governance-export/1"
DETAILS_SERIALISATION = "compact JSON, keys in document order, UTF-8, no whitespace"

# One lock for the whole table, so entries are appended one at a time and the
# chain stays linear. Derived from the table name so it cannot collide with a
# lock taken elsewhere for another reason.
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"dpolens.governance_log").digest()[:8], "big", signed=True
)

USER_CREATED = "user.created"
USER_DEACTIVATED = "user.deactivated"
USER_ACTIVATED = "user.activated"
USER_ROLE_GRANTED = "user.role_granted"
USER_ROLE_REVOKED = "user.role_revoked"
ROLE_CREATED = "role.created"
ROLE_SEEDED = "role.seeded"
ROLE_DELETED = "role.deleted"
ROLE_PERMISSIONS_CHANGED = "role.permissions_changed"
GOVERNANCE_EXPORTED = "governance_log.exported"


@dataclass(frozen=True)
class Actor:
    """Who is acting, as far as the system can honestly tell.

    A CLI action has no user id: whoever holds the database URL is outside the
    identity system, and naming a person there would be a claim nothing supports.
    """

    user_id: uuid.UUID | None = None
    pat_id: uuid.UUID | None = None
    via: str = "api"
    identity: Mapping[str, str] = field(default_factory=dict)


def cli_actor() -> Actor:
    """The actor for an action taken with shell access.

    The operating system user and hostname are recorded because they are what
    can be known, not because they authenticate anyone.
    """
    try:
        os_user = getpass.getuser()
    except Exception:  # pragma: no cover - no password database in some sandboxes
        os_user = "unknown"
    return Actor(via="cli", identity={"os_user": os_user, "host": socket.gethostname()})


def canonical_json(value: Mapping[str, Any]) -> str:
    """The exact text that goes into the database and into the hash."""
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def timestamp_text(value: datetime) -> str:
    """UTC with exactly six fractional digits, which is what Postgres keeps."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _field(value: bytes | str | None) -> bytes:
    raw = b"" if value is None else value.encode() if isinstance(value, str) else value
    return len(raw).to_bytes(8, "big") + raw


def entry_hash(
    *,
    prev_hash: bytes,
    occurred_at: datetime,
    actor_user_id: uuid.UUID | None,
    actor_pat_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: str,
    details_text: str,
    hash_version: int = HASH_VERSION,
) -> bytes:
    """Recipe v1, as described at the top of this module."""
    parts = (
        _field(str(hash_version)),
        _field(prev_hash),
        _field(timestamp_text(occurred_at)),
        _field(str(actor_user_id) if actor_user_id is not None else None),
        _field(str(actor_pat_id) if actor_pat_id is not None else None),
        _field(action),
        _field(target_type),
        _field(target_id),
        _field(details_text),
    )
    return hashlib.sha256(b"".join(parts)).digest()


def genesis_hash(session: Session) -> bytes:
    """What the first entry's prev_hash has to be, for this instance."""
    return genesis_for(instance_id(session))


def genesis_for(identifier: uuid.UUID) -> bytes:
    return hashlib.sha256(str(identifier).encode()).digest()


def record(
    session: Session,
    *,
    actor: Actor,
    action: str,
    target_type: str,
    target_id: str,
    details: Mapping[str, Any] | None = None,
) -> int:
    """Append one entry and return its sequence number.

    The lock is held until the transaction ends, so two concurrent writers
    cannot read the same predecessor and fork the chain.
    """
    session.execute(select(func.pg_advisory_xact_lock(LOCK_KEY)))

    previous = session.scalars(
        select(GovernanceEntry.entry_hash).order_by(GovernanceEntry.seq.desc()).limit(1)
    ).first()
    prev_hash = previous if previous is not None else genesis_hash(session)

    occurred_at = datetime.now(UTC)
    body: dict[str, Any] = dict(details or {})
    body["via"] = actor.via
    if actor.identity:
        body["actor"] = dict(actor.identity)
    details_text = canonical_json(body)

    digest = entry_hash(
        prev_hash=prev_hash,
        occurred_at=occurred_at,
        actor_user_id=actor.user_id,
        actor_pat_id=actor.pat_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details_text=details_text,
    )

    seq = session.execute(
        insert(GovernanceEntry)
        .values(
            occurred_at=occurred_at,
            actor_user_id=actor.user_id,
            actor_pat_id=actor.pat_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            # Cast the text rather than letting the driver serialise a dict, so
            # the bytes that were hashed are the bytes that are stored.
            details=cast(literal(details_text, Text()), JSON),
            prev_hash=prev_hash,
            entry_hash=digest,
            hash_version=HASH_VERSION,
        )
        .returning(GovernanceEntry.seq)
    ).scalar_one()
    return int(seq)


@dataclass(frozen=True)
class EntryRow:
    """One entry as verification and export see it, with `details` as raw text."""

    seq: int
    occurred_at: datetime
    actor_user_id: uuid.UUID | None
    actor_pat_id: uuid.UUID | None
    action: str
    target_type: str
    target_id: str
    details_text: str
    prev_hash: bytes
    entry_hash: bytes
    hash_version: int

    def recomputed(self) -> bytes:
        return entry_hash(
            prev_hash=self.prev_hash,
            occurred_at=self.occurred_at,
            actor_user_id=self.actor_user_id,
            actor_pat_id=self.actor_pat_id,
            action=self.action,
            target_type=self.target_type,
            target_id=self.target_id,
            details_text=self.details_text,
            hash_version=self.hash_version,
        )


@dataclass(frozen=True)
class VerifyReport:
    entries: int
    first_broken_seq: int | None = None
    reason: str | None = None
    out_of_order: tuple[int, ...] = ()
    anchored_to_genesis: bool = True

    @property
    def ok(self) -> bool:
        return self.first_broken_seq is None and not self.out_of_order


def read_entries(
    session: Session, *, from_seq: int | None = None, to_seq: int | None = None
) -> list[EntryRow]:
    """Entries in sequence order, with `details` read as the text that was stored.

    `details::text` is asked for on purpose: recomputing a hash from a parsed
    and re-serialised object would test the serialiser, not the chain.
    """
    query = select(
        GovernanceEntry.seq,
        GovernanceEntry.occurred_at,
        GovernanceEntry.actor_user_id,
        GovernanceEntry.actor_pat_id,
        GovernanceEntry.action,
        GovernanceEntry.target_type,
        GovernanceEntry.target_id,
        cast(GovernanceEntry.details, Text()).label("details_text"),
        GovernanceEntry.prev_hash,
        GovernanceEntry.entry_hash,
        GovernanceEntry.hash_version,
    ).order_by(GovernanceEntry.seq)
    if from_seq is not None:
        query = query.where(GovernanceEntry.seq >= from_seq)
    if to_seq is not None:
        query = query.where(GovernanceEntry.seq <= to_seq)

    return [
        EntryRow(
            seq=int(row.seq),
            occurred_at=row.occurred_at,
            actor_user_id=row.actor_user_id,
            actor_pat_id=row.actor_pat_id,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            details_text=row.details_text,
            prev_hash=bytes(row.prev_hash),
            entry_hash=bytes(row.entry_hash),
            hash_version=int(row.hash_version),
        )
        for row in session.execute(query)
    ]


def verify_rows(
    rows: Sequence[EntryRow], *, expected_first_prev: bytes, anchored: bool
) -> VerifyReport:
    """Check a run of entries, wherever they were read from.

    The same function serves the live table and an exported file, so an auditor
    checking a directory runs the code the instance runs on itself.
    """
    for row in rows:
        if row.hash_version != HASH_VERSION:
            return VerifyReport(
                len(rows),
                row.seq,
                f"entry uses hash version {row.hash_version}, which this build cannot check",
                anchored_to_genesis=anchored,
            )
        if row.recomputed() != row.entry_hash:
            return VerifyReport(
                len(rows),
                row.seq,
                "the entry's fields do not match its own hash",
                anchored_to_genesis=anchored,
            )

    # The links are checked separately from the hashes, so a report can say
    # which of the two is wrong rather than only that something is.
    by_predecessor: dict[bytes, EntryRow] = {}
    for row in rows:
        if row.prev_hash in by_predecessor:
            return VerifyReport(
                len(rows),
                row.seq,
                f"two entries claim to follow the same one, {by_predecessor[row.prev_hash].seq} "
                "is the other",
                anchored_to_genesis=anchored,
            )
        by_predecessor[row.prev_hash] = row

    order: list[int] = []
    cursor = expected_first_prev
    while cursor in by_predecessor:
        row = by_predecessor.pop(cursor)
        order.append(row.seq)
        cursor = row.entry_hash

    if by_predecessor:
        orphan = min(by_predecessor.values(), key=lambda row: row.seq)
        reason = (
            "the chain does not start where it should"
            if not order
            else "an entry does not link to the one before it"
        )
        return VerifyReport(len(rows), orphan.seq, reason, anchored_to_genesis=anchored)

    out_of_order = tuple(order) if order != sorted(order) else ()
    return VerifyReport(len(rows), None, None, out_of_order, anchored)


def verify(session: Session) -> VerifyReport:
    """Recompute the whole chain and report the first thing that is wrong."""
    rows = read_entries(session)
    return verify_rows(rows, expected_first_prev=genesis_hash(session), anchored=True)
