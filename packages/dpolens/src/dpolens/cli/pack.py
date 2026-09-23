"""Pack commands.

`build` is maintainer tooling: a pack is converted once, reviewed by a person
and committed, so no instance ever parses law text for itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated
from xml.etree import ElementTree

import typer

from dpolens.engine.packs.format import Clause
from dpolens.engine.packs.formex import parse_articles, parse_recitals, text_of
from dpolens.engine.packs.load import load_pack
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
) -> None:
    """Load a pack into this instance.

    Loading the same pack version twice changes nothing, so running it again
    after a restart is safe.
    """
    with session_scope(load_settings()) as session:
        result = load_pack(session, directory)

    if result.already_loaded:
        typer.echo(f"{result.pack_slug} {result.version} is already loaded")
        return
    typer.echo(
        f"Loaded {result.pack_slug} {result.version}: "
        f"{result.clauses_loaded} clauses across {result.documents_loaded} documents"
    )
