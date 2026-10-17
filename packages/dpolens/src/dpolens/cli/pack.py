"""Pack commands.

`build` is maintainer tooling: a pack is converted once, reviewed by a person
and committed, so no instance ever parses law text for itself. `archive` makes the
file a release publishes. `update` and `import` load a newer version of a law
from a release or from a file, and nothing else ever does: an upgrade of the app
leaves the laws an instance has as they are.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated
from xml.etree import ElementTree

import typer

from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.packs.archive import (
    CHECKSUM_SUFFIX,
    ArchiveError,
    read_checksum,
    write_archive,
)
from dpolens.engine.packs.format import Clause, PackFormatError, read_pack_metadata
from dpolens.engine.packs.formex import parse_articles, parse_recitals, text_of
from dpolens.engine.packs.install import install_archive, loaded
from dpolens.engine.packs.load import (
    LoadResult,
    load_pack,
    loaded_packs,
    loaded_version,
    version_key,
)
from dpolens.engine.packs.releases import fetch, newest, pack_releases
from dpolens.engine.packs.write import check_coverage, link_clauses, write_document
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(name="pack", help="Build, inspect and load law packs.", no_args_is_help=True)


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@app.command()
def build(
    out: Annotated[Path, typer.Option(help="Pack directory to write into")],
    articles: Annotated[Path, typer.Option(help="Formex XML holding the enacting terms")],
    articles_slug: Annotated[str, typer.Option(help="Document slug for the articles")],
    recitals: Annotated[Path | None, typer.Option(help="Formex XML holding the preamble")] = None,
    recitals_slug: Annotated[
        str | None, typer.Option(help="Document slug for the recitals")
    ] = None,
) -> None:
    """Convert Formex XML into pack files.

    A consolidated EU text carries the current articles and an empty preamble,
    so recitals come from the original act and the two are given separately.
    """
    written: list[tuple[str, int, str]] = []

    article_clauses = parse_articles(articles, articles_slug)
    _check_articles(articles, article_clauses)
    count = write_document(out / articles_slug, article_clauses, articles_slug)
    written.append((articles_slug, count, _checksum(articles)))
    _report_dangling(article_clauses, articles_slug)

    if recitals is not None:
        if recitals_slug is None:
            raise typer.BadParameter("--recitals-slug is required with --recitals")
        recital_clauses = parse_recitals(recitals, recitals_slug)
        count = write_document(out / recitals_slug, recital_clauses, recitals_slug)
        written.append((recitals_slug, count, _checksum(recitals)))

    typer.echo(f"Wrote {sum(count for _, count, _ in written)} clause files to {out}")
    for slug, count, checksum in written:
        typer.echo(f"  {slug}: {count} clauses, source sha256 {checksum}")
    typer.echo("\nSet expected_clauses in pack.yaml to these counts, and record the checksums.")


def _check_articles(path: Path, clauses: list[Clause]) -> None:
    """Compare every article against its source element, character by character."""
    root = ElementTree.parse(path).getroot()
    elements = list(root.iter("ARTICLE"))
    if len(elements) != len(clauses):
        raise typer.BadParameter(
            f"{path}: {len(elements)} articles in the source, {len(clauses)} converted"
        )
    for element, clause in zip(elements, clauses, strict=True):
        check_coverage(text_of(element), clause)


def _report_dangling(clauses: list[Clause], document_slug: str) -> None:
    _, dangling = link_clauses(clauses, document_slug)
    if not dangling:
        return
    typer.echo(f"\n{len(dangling)} references point at clauses this document does not have:")
    for key, reference in dangling[:10]:
        typer.echo(f"  {key} -> {reference.target_key} ({reference.raw_text})")
    if len(dangling) > 10:
        typer.echo(f"  ... and {len(dangling) - 10} more")


@app.command()
def load(
    directory: Annotated[Path, typer.Argument(help="Pack directory, for example packs/gdpr")],
    unless_loaded: Annotated[
        bool,
        typer.Option(
            "--unless-loaded",
            help=(
                "Leave alone a pack this instance has any version of, and say when the "
                "folder's is newer. Starting an instance does this."
            ),
        ),
    ] = False,
) -> None:
    """Load a pack into this instance.

    Loading the same pack version twice changes nothing, so running it again
    after a restart is safe. A version older than the one loaded is refused.
    """
    with session_scope(load_settings()) as session:
        if unless_loaded:
            metadata = read_pack_metadata(directory)
            current = loaded_version(session, metadata.slug)
            if current is not None:
                if version_key(metadata.version) > version_key(current):
                    typer.echo(
                        f"{metadata.slug} {metadata.version} is in {directory}, and this instance "
                        f"has {current}. `dpolens pack load {directory}` loads it."
                    )
                else:
                    typer.echo(f"{metadata.slug} {current} is loaded")
                return
        result = load_pack(session, directory)
        loaded(session, result, source="image" if unless_loaded else "folder", actor=cli_actor())
    _report(result)


def _report(result: LoadResult, *, embedded_later: bool = False) -> None:
    if result.already_loaded:
        typer.echo(f"{result.pack_slug} {result.version} is already loaded")
        return
    documents = "document" if result.documents_loaded == 1 else "documents"
    typer.echo(
        f"Loaded {result.pack_slug} {result.version}: "
        f"{result.clauses_loaded} clauses across {result.documents_loaded} {documents}"
    )
    if embedded_later:
        typer.echo("Its words are searchable now, and its meaning once the worker has embedded it.")


@app.command()
def archive(
    directory: Annotated[Path, typer.Argument(help="Pack directory, for example packs/gdpr")],
    out: Annotated[Path, typer.Option(help="Where to write the file and its checksum")] = Path(
        "dist"
    ),
    tag: Annotated[
        str | None,
        typer.Option(help="The release's tag, pack/<slug>/<version>, which has to match the pack"),
    ] = None,
) -> None:
    """Write a pack archive, the one file a release publishes, with its SHA-256 beside it."""
    metadata = read_pack_metadata(directory)
    if tag is not None and tag != f"pack/{metadata.slug}/{metadata.version}":
        raise PackFormatError(
            f"the tag {tag} does not name {metadata.slug} {metadata.version}, "
            f"which {directory / 'pack.yaml'} holds"
        )
    licence = directory.parent / "LICENSE"
    if not licence.is_file():
        raise PackFormatError(f"{licence} is missing, and every pack archive carries it")
    path = write_archive(directory, licence, out, metadata.slug, metadata.version)
    typer.echo(f"{path}\n{path}{CHECKSUM_SUFFIX}")


@app.command()
def update(
    slug: Annotated[
        str | None,
        typer.Argument(help="The pack to update, for example gdpr. Without it, nothing is loaded."),
    ] = None,
) -> None:
    """Load the newest version of a law pack from GitHub.

    The releases read are those of the repository DPOLENS_PACKS_REPOSITORY names,
    alkhatibdev/dpolens unless it is set.

    Without a pack named, this lists each pack the instance has and whether a newer
    version is published. Nothing is loaded unless it is asked for by name.
    """
    settings = load_settings()
    with session_scope(settings) as session:
        current = loaded_packs(session)
    releases = pack_releases(settings.packs_repository)

    if slug is None:
        for name, version in sorted(current.items()):
            release = newest(releases, name, version)
            if release is None:
                typer.echo(f"{name} {version}: nothing newer is published")
            else:
                typer.echo(
                    f"{name} {version}: {release.version} is published. "
                    f"`dpolens pack update {name}` loads it."
                )
        return

    if slug not in current:
        raise PackFormatError(
            f"this instance has no {slug}. `dpolens pack update` lists the packs it has."
        )
    release = newest(releases, slug, current[slug])
    if release is None:
        typer.echo(f"{slug} {current[slug]}: nothing newer is published")
        return
    data = fetch(release.archive_url)
    checksum = read_checksum(fetch(release.checksum_url).decode("utf-8"))
    with session_scope(settings) as session:
        result = install_archive(
            session,
            data,
            checksum,
            source="update",
            actor=cli_actor(),
            expected=(release.slug, release.version),
            repository=settings.packs_repository,
        )
    _report(result, embedded_later=True)


@app.command("import")
def import_(
    file: Annotated[
        Path, typer.Argument(help="A pack archive, for example dpolens-pack-gdpr-2026.2.tar.gz")
    ],
    sha256: Annotated[
        str | None,
        typer.Option(
            help="The file's SHA-256 from its release. Without it, the .sha256 beside it."
        ),
    ] = None,
) -> None:
    """Load a pack archive brought by hand, for an instance with no way to the internet."""
    if sha256 is None:
        beside = file.with_name(f"{file.name}{CHECKSUM_SUFFIX}")
        if not beside.is_file():
            raise ArchiveError(
                f"there is no checksum to check {file.name} against: put {beside.name} from "
                "its release beside it, or pass --sha256"
            )
        sha256 = beside.read_text(encoding="utf-8")
    checksum = read_checksum(sha256)
    with session_scope(load_settings()) as session:
        result = install_archive(
            session, file.read_bytes(), checksum, source="file", actor=cli_actor()
        )
    _report(result, embedded_later=True)
