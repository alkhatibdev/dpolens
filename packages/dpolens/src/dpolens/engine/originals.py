"""Original files, kept on a volume behind a storage interface.

The database keeps a key, a size and a SHA-256 for each original, never a path, so the same
key means the same file on a disk today or in object storage later. A file is written before
the version that points at it is committed: a failure can leave a stray file, which the
daily purge removes, but never a version pointing at nothing. A file is never overwritten,
and it is checked against its size and hash every time it is read.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

KEY = re.compile(r"^sha256/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}$")


class OriginalUnavailable(Exception):
    """An original is missing, or no longer what was stored, which is an error, not a download."""


class OriginalsUnwritable(Exception):
    """The folder for originals cannot be written to, which is the instance's setup to fix."""


@dataclass(frozen=True)
class Stored:
    key: str
    size: int
    sha256: str


def key_for(digest: str) -> str:
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


class Originals(Protocol):
    def put(self, data: bytes) -> Stored: ...

    def get(self, stored: Stored) -> bytes: ...

    def listing(self) -> Iterable[tuple[str, float]]:
        """Every stored key, with when it was written, for removing strays."""
        ...

    def remove(self, key: str) -> None: ...


class Directory:
    """Originals in a directory, one file for each hash."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, key: str) -> Path:
        if not KEY.match(key):
            raise OriginalUnavailable(f"{key!r} is not an original's key.")
        return self.root / key

    def put(self, data: bytes) -> Stored:
        digest = hashlib.sha256(data).hexdigest()
        stored = Stored(key=key_for(digest), size=len(data), sha256=digest)
        path = self.path(stored.key)
        if path.exists():
            # Two uploads of the same file share one, and one that no longer matches its
            # name is reported rather than replaced.
            self.get(stored)
            return stored
        partial = path.with_name(f"{path.name}.{uuid.uuid4().hex}.partial")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with partial.open("xb") as written:
                written.write(data)
                written.flush()
                os.fsync(written.fileno())
            os.replace(partial, path)
        except PermissionError as refused:
            raise OriginalsUnwritable(
                f"Original files cannot be written to {self.root}. Set DPOLENS_ORIGINALS_DIR "
                "to a folder this user can write to."
            ) from refused
        return stored

    def get(self, stored: Stored) -> bytes:
        path = self.path(stored.key)
        try:
            data = path.read_bytes()
        except FileNotFoundError as missing:
            raise OriginalUnavailable(f"The original file {stored.key} is missing.") from missing
        if len(data) != stored.size or hashlib.sha256(data).hexdigest() != stored.sha256:
            raise OriginalUnavailable(
                f"The original file {stored.key} has changed since it was stored."
            )
        return data

    def listing(self) -> Iterable[tuple[str, float]]:
        base = self.root / "sha256"
        if not base.exists():
            return
        for path in base.glob("*/*/*"):
            key = path.relative_to(self.root).as_posix()
            if KEY.match(key):
                yield key, path.stat().st_mtime

    def remove(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


def strays(originals: Originals, referenced: set[str], grace_seconds: float) -> list[str]:
    """Stored files no version points at, written longer ago than the grace period.

    The grace period is what lets an upload write its file, then its version, without the
    purge removing the file in between.
    """
    now = time.time()
    return [
        key
        for key, written in originals.listing()
        if key not in referenced and now - written > grace_seconds
    ]
