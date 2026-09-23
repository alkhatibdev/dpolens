"""Reading a clause from the corpus."""

from __future__ import annotations

from datetime import date
from typing import Annotated

import typer

from dpolens.engine.documents.read import ClauseNotFound, ClauseView, get_clause, get_subtree
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(name="clause", help="Read clauses by canonical key.", no_args_is_help=True)

WRAP = 88


@app.command()
def show(
    key: Annotated[str, typer.Argument(help="Canonical key, for example gdpr:art-17")],
    subtree: Annotated[bool, typer.Option(help="Include everything beneath the clause")] = False,
    lang: Annotated[
        str | None, typer.Option(help="Preferred language, if there are several")
    ] = None,
    as_of: Annotated[
        str | None, typer.Option(help="Read the version in force on this date, YYYY-MM-DD")
    ] = None,
) -> None:
    """Print a clause, its breadcrumb and the links its text states."""
    on = date.fromisoformat(as_of) if as_of else None

    try:
        with session_scope(load_settings()) as session:
            detail = get_clause(session, key, lang, on)
            descendants = get_subtree(session, key, lang, on)[1:] if subtree else []
    except ClauseNotFound as missing:
        typer.secho(str(missing), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from missing

    clause = detail.clause
    typer.secho(
        f"{clause.document_title} ({clause.document_slug}), in force {clause.effective_date}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    if detail.breadcrumb:
        trail = " > ".join(_name(parent) for parent in detail.breadcrumb)
        typer.secho(trail, fg=typer.colors.BRIGHT_BLACK)

    typer.echo("")
    _print_clause(clause, indent=0)

    # A clause with children is incomplete without them, whether or not it has
    # text of its own. A lead-in that ends "one of the following applies:" is
    # the worst case: the reader is left exactly where the list should be.
    if not subtree and detail.children:
        labels = ", ".join(_name(child) for child in detail.children[:6])
        more = ", ..." if len(detail.children) > 6 else ""
        # Labels often end in a full stop of their own, as in "1.", "2."
        listed = f"Contains {len(detail.children)}: {labels}{more}".rstrip(".")
        typer.secho(f"{listed}. Read them with --subtree.", fg=typer.colors.BRIGHT_BLACK)

    for descendant in descendants:
        typer.echo("")
        _print_clause(descendant, indent=descendant.depth - clause.depth)

    if detail.cross_references:
        typer.echo("")
        typer.secho("Refers to:", fg=typer.colors.BRIGHT_BLACK)
        for target, wording in detail.cross_references:
            typer.echo(f"  {target}  ({wording})")


def _name(clause: ClauseView) -> str:
    return clause.heading or clause.label or clause.key


def _print_clause(clause: ClauseView, indent: int) -> None:
    pad = "  " * indent
    title = " ".join(part for part in (clause.label, clause.heading) if part)
    header = f"{pad}{title}" if title else pad
    notes = [clause.key]
    if not clause.is_normative:
        notes.append("non-normative")
    if not clause.is_authoritative:
        notes.append(f"{clause.lang}, translation")

    typer.secho(f"{header}  [{', '.join(notes)}]".lstrip(), bold=True)
    for line in _wrap(clause.text, WRAP - len(pad)):
        typer.echo(f"{pad}{line}")


def _wrap(text: str, width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    for paragraph in text.split("\n\n"):
        current = ""
        for word in paragraph.split():
            if current and len(current) + 1 + len(word) > width:
                lines.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        if current:
            lines.append(current)
    return lines
