"""Original files: stored once under their hash, checked whenever they are read."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from dpolens.engine.originals import (
    Directory,
    OriginalsUnwritable,
    OriginalUnavailable,
    Stored,
    strays,
)

POLICY = b"# Retention\n\n4.1 Customer records are kept for 2 years.\n"


def test_a_file_comes_back_as_it_was_stored(tmp_path: Path) -> None:
    originals = Directory(tmp_path)

    stored = originals.put(POLICY)

    assert originals.get(stored) == POLICY
    assert stored.size == len(POLICY)
    assert stored.key == f"sha256/{stored.sha256[:2]}/{stored.sha256[2:4]}/{stored.sha256}"


def test_the_same_file_uploaded_twice_is_kept_once(tmp_path: Path) -> None:
    originals = Directory(tmp_path)

    assert originals.put(POLICY) == originals.put(POLICY)
    assert len(list(originals.listing())) == 1


def test_a_file_that_changed_is_an_error_rather_than_a_download(tmp_path: Path) -> None:
    originals = Directory(tmp_path)
    stored = originals.put(POLICY)
    originals.path(stored.key).write_bytes(POLICY.replace(b"2 years", b"9 years"))

    with pytest.raises(OriginalUnavailable, match="has changed"):
        originals.get(stored)
    with pytest.raises(OriginalUnavailable):
        originals.put(POLICY)


def test_a_missing_file_is_an_error(tmp_path: Path) -> None:
    originals = Directory(tmp_path)
    stored = originals.put(POLICY)
    originals.remove(stored.key)

    with pytest.raises(OriginalUnavailable, match="missing"):
        originals.get(stored)


def test_a_key_cannot_reach_outside_the_folder(tmp_path: Path) -> None:
    originals = Directory(tmp_path / "originals")

    with pytest.raises(OriginalUnavailable):
        originals.get(Stored(key="../../etc/passwd", size=0, sha256="0" * 64))


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to any folder")
def test_a_folder_it_cannot_write_to_names_the_setting(tmp_path: Path) -> None:
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(OriginalsUnwritable, match="DPOLENS_ORIGINALS_DIR"):
            Directory(tmp_path / "originals").put(POLICY)
    finally:
        tmp_path.chmod(0o700)


def test_a_stray_is_a_file_nothing_points_at_once_its_grace_has_passed(tmp_path: Path) -> None:
    originals = Directory(tmp_path)
    old = originals.put(b"an upload that never finished")
    kept = originals.put(POLICY)
    fresh = originals.put(b"an upload still in progress")
    day_ago = time.time() - 2 * 24 * 60 * 60
    for stored in (old, kept):
        os.utime(originals.path(stored.key), (day_ago, day_ago))

    assert strays(originals, {kept.key}, grace_seconds=24 * 60 * 60) == [old.key]
    assert fresh.key not in strays(originals, {kept.key}, grace_seconds=24 * 60 * 60)
