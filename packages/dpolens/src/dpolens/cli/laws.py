"""Law commands: which laws apply to the organisation, and so what a search covers."""

from __future__ import annotations

from typing import Annotated

import typer

from dpolens.cli import ask
from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.packs.selection import loaded_laws, select_laws, selected_laws
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="laws",
    help="Choose which laws apply to the organisation, and so what a search covers.",
    no_args_is_help=True,
)

NOTHING_YET = "No laws are selected yet, so nothing is searched."


@app.command(name="list")
def list_() -> None:
    """List every loaded law and which of them a search covers."""
    with session_scope(load_settings()) as session:
        selected = selected_laws(session) or []
        for pack in loaded_laws(session):
            covered = pack.slug in selected
            typer.echo(f"{pack.slug:16} {'searched' if covered else '-':9} {pack.name}")
    if not selected:
        typer.echo(f"\n{NOTHING_YET} Choose with: dpolens laws select")


@app.command()
def select(
    slugs: Annotated[
        list[str] | None,
        typer.Argument(help="The laws that apply, by slug. Left out, a checklist in a terminal"),
    ] = None,
) -> None:
    """Make these exactly the laws that apply. Written to the governance log."""
    with session_scope(load_settings()) as session:
        if not slugs:
            if not ask.interactive():
                raise typer.BadParameter(
                    "name at least one, such as gdpr, when there is no terminal to ask in",
                    param_hint="'SLUGS...'",
                )
            slugs = ask.checklist(
                "Which laws apply to your organisation",
                [(pack.slug, f"{pack.name}, {pack.jurisdiction}") for pack in loaded_laws(session)],
                checked=selected_laws(session) or (),
                at_least_one=True,
            )
        chosen = select_laws(session, slugs, actor=cli_actor())
    typer.echo(f"Selected: {', '.join(chosen)}. A search covers these and the policies.")
