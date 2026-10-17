"""A pack archive: one version of a law pack as one file, what a release publishes.

The checksum is what makes a downloaded law trustworthy, so it is checked before
anything is read, and nothing in the file may land outside the folder it is
opened in.
"""

from __future__ import annotations

import io
import re
import tarfile
from pathlib import Path

import pytest

from dpolens.engine.packs.archive import (
    ArchiveError,
    open_archive,
    read_checksum,
    sha256_of,
    write_archive,
)

REPO = Path(__file__).resolve().parents[2]
LICENCE = REPO / "packs" / "LICENSE"
TESTLAW = REPO / "tests" / "fixtures" / "packs" / "testlaw"


def written(out: Path) -> Path:
    return write_archive(TESTLAW, LICENCE, out, "testlaw", "2026.1")


def tar_of(entries: dict[str, bytes]) -> bytes:
    """A gzipped tar holding exactly these entries, for files no release would make."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_the_file_is_named_for_the_pack_and_its_version(tmp_path: Path) -> None:
    assert written(tmp_path).name == "dpolens-pack-testlaw-2026.1.tar.gz"


def test_the_same_folder_makes_the_same_file(tmp_path: Path) -> None:
    assert written(tmp_path / "one").read_bytes() == written(tmp_path / "two").read_bytes()


def test_it_holds_the_licence_and_the_pack_folder_as_it_is(tmp_path: Path) -> None:
    with tarfile.open(written(tmp_path)) as tar:
        names = tar.getnames()
        pack_yaml = tar.extractfile("testlaw/pack.yaml")
        assert pack_yaml is not None
        assert pack_yaml.read() == (TESTLAW / "pack.yaml").read_bytes()

    assert names == [
        "LICENSE",
        "testlaw/pack.yaml",
        "testlaw/testlaw/art-5.md",
        "testlaw/testlaw/art-6.md",
        "testlaw/testlaw-recitals/rec-12.md",
    ]


def test_its_checksum_sits_beside_it_as_sha256sum_writes_one(tmp_path: Path) -> None:
    archive = written(tmp_path)

    line = (tmp_path / f"{archive.name}.sha256").read_text(encoding="utf-8")

    assert line == f"{sha256_of(archive.read_bytes())}  {archive.name}\n"


def test_opening_gives_the_pack_folder(tmp_path: Path) -> None:
    data = written(tmp_path / "dist").read_bytes()

    folder = open_archive(data, sha256_of(data), tmp_path / "opened")

    assert folder == tmp_path / "opened" / "testlaw"
    assert (folder / "pack.yaml").read_bytes() == (TESTLAW / "pack.yaml").read_bytes()


def test_a_changed_file_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    data = written(tmp_path / "dist").read_bytes()
    changed = data[:-1] + bytes([data[-1] ^ 1])

    with pytest.raises(ArchiveError, match="changed or damaged on its way here"):
        open_archive(changed, sha256_of(data), tmp_path / "opened")

    assert not (tmp_path / "opened").exists()


def test_a_file_with_two_packs_in_it_is_refused(tmp_path: Path) -> None:
    data = tar_of({"LICENSE": b"l", "one/pack.yaml": b"a", "two/pack.yaml": b"b"})

    with pytest.raises(ArchiveError, match="the licence and one pack folder"):
        open_archive(data, sha256_of(data), tmp_path / "opened")


def test_a_file_reaching_outside_its_folder_is_refused(tmp_path: Path) -> None:
    data = tar_of({"LICENSE": b"l", "pack/pack.yaml": b"a", "pack/../../escaped.txt": b"x"})

    with pytest.raises(ArchiveError, match="not a pack archive that can be read"):
        open_archive(data, sha256_of(data), tmp_path / "inside" / "opened")

    assert not (tmp_path / "escaped.txt").exists()


def test_a_checksum_reads_from_sha256sum_or_pasted_alone() -> None:
    digest = "ab" * 32

    assert read_checksum(f"{digest}  dpolens-pack-gdpr-2026.1.tar.gz\n") == digest
    assert read_checksum(digest.upper()) == digest
    with pytest.raises(ArchiveError, match=re.escape("64 hexadecimal characters")):
        read_checksum("not a checksum")
