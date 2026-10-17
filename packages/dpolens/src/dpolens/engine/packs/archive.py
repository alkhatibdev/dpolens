"""A pack archive: one version of a pack as one file, the way a release publishes it.

The file is a gzipped tar of the pack's folder as it is in the repository, beside
the licence that covers every pack, named for the pack and its version. Its
SHA-256 travels in a file of its own, in the format `sha256sum` writes, so it can
be checked with nothing but the operating system's own tools.

Entries are sorted and owners, permissions and times are fixed, so the archive
depends on the files alone. Opening one checks the checksum before anything is
read, and extracts nothing that could land outside the folder it is opened in.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import re
import tarfile
from pathlib import Path

LICENCE = "LICENSE"
CHECKSUM_SUFFIX = ".sha256"
SHA256 = re.compile(r"[0-9a-f]{64}")


class ArchiveError(Exception):
    """A pack archive that cannot be trusted or read, said in a sentence."""


def archive_name(slug: str, version: str) -> str:
    return f"dpolens-pack-{slug}-{version}.tar.gz"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_archive(pack_dir: Path, licence: Path, out_dir: Path, slug: str, version: str) -> Path:
    """Write the pack's file and its checksum beside it, and return the file's path."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        _add(tar, licence, LICENCE)
        for path in sorted(pack_dir.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                _add(tar, path, f"{slug}/{path.relative_to(pack_dir).as_posix()}")
    compressed = io.BytesIO()
    # No file name and no time in the gzip header, so they cannot change the bytes.
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as packed:
        packed.write(buffer.getvalue())

    out_dir.mkdir(parents=True, exist_ok=True)
    name = archive_name(slug, version)
    archive = out_dir / name
    archive.write_bytes(compressed.getvalue())
    (out_dir / f"{name}{CHECKSUM_SUFFIX}").write_text(
        f"{sha256_of(compressed.getvalue())}  {name}\n", encoding="utf-8"
    )
    return archive


def _add(tar: tarfile.TarFile, path: Path, name: str) -> None:
    data = path.read_bytes()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def read_checksum(text: str) -> str:
    """The SHA-256 a checksum file holds, whether `sha256sum` wrote it or a person pasted it."""
    found = text.strip().split()[0].lower() if text.strip() else ""
    if not SHA256.fullmatch(found):
        raise ArchiveError("the checksum is not a SHA-256: it should be 64 hexadecimal characters")
    return found


def open_archive(data: bytes, expected_sha256: str, into: Path) -> Path:
    """Check a pack archive against its checksum, extract it, and return the pack's folder.

    Nothing is extracted until the checksum matches. The file has to hold the
    licence and exactly one pack folder, and nothing else.
    """
    actual = sha256_of(data)
    if actual != expected_sha256.lower():
        raise ArchiveError(
            f"the file's SHA-256 is {actual}, not the {expected_sha256.lower()} it was published "
            "with: it was changed or damaged on its way here"
        )
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = tar.getmembers()
            tops = {member.name.split("/", 1)[0] for member in members}
            folders = sorted(tops - {LICENCE})
            if len(folders) != 1 or not any(member.name == LICENCE for member in members):
                raise ArchiveError(
                    "a pack archive holds the licence and one pack folder, and this one does not"
                )
            # The "data" filter refuses links, devices, absolute paths and anything
            # that would land outside the folder.
            tar.extractall(into, filter="data")
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ArchiveError(f"the file is not a pack archive that can be read: {error}") from error
    return into / folders[0]
