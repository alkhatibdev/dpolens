"""A law version loaded from where it came: the image, a folder, an update or a file.

Whichever way it arrives, a version that is stored is written to the governance
log with where it came from, and its clauses are queued for the worker to embed:
its words are searchable at once, and its meaning once the worker has run.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from sqlalchemy.orm import Session

from dpolens.engine.jobs import queue_indexing
from dpolens.engine.logs.governance import LAWS_PACK_LOADED, Actor, record
from dpolens.engine.packs.archive import ArchiveError, open_archive
from dpolens.engine.packs.format import read_pack_metadata
from dpolens.engine.packs.load import LoadResult, load_pack

Source = Literal["image", "folder", "update", "file"]


def loaded(
    session: Session,
    result: LoadResult,
    *,
    source: Source,
    actor: Actor,
    sha256: str | None = None,
    repository: str | None = None,
) -> None:
    """Record a version that was stored, and queue its clauses for embedding.

    An update records the repository it was read from, which is not always this
    project's: an instance can be pointed at a fork that publishes its own packs.
    """
    if result.already_loaded:
        return
    for version_id in result.version_ids:
        queue_indexing(session, version_id)
    details = {"pack": result.pack_slug, "version": result.version, "source": source}
    if sha256:
        details["sha256"] = sha256
    if repository:
        details["repository"] = repository
    record(
        session,
        actor=actor,
        action=LAWS_PACK_LOADED,
        target_type="pack",
        target_id=result.pack_slug,
        details=details,
    )


def install_archive(
    session: Session,
    data: bytes,
    sha256: str,
    *,
    source: Source,
    actor: Actor,
    expected: tuple[str, str] | None = None,
    repository: str | None = None,
) -> LoadResult:
    """Check a pack archive, load the version it holds, and record it.

    `expected` is the pack and version a release said the file holds, which the
    file has to agree with.
    """
    with TemporaryDirectory(prefix="dpolens-pack-") as folder:
        pack_dir = open_archive(data, sha256, Path(folder))
        metadata = read_pack_metadata(pack_dir)
        if expected is not None and (metadata.slug, metadata.version) != expected:
            raise ArchiveError(
                f"the file holds {metadata.slug} {metadata.version}, not the "
                f"{expected[0]} {expected[1]} its release names"
            )
        result = load_pack(session, pack_dir)
    loaded(session, result, source=source, actor=actor, sha256=sha256, repository=repository)
    return result
