"""Law commands: which laws apply to the organisation, and so what a search covers."""

from __future__ import annotations

from typing import Annotated

import typer

from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.packs.selection import (
    clear_selection,
    loaded_laws,
    select_laws,
    selected_laws,
)
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="laws",
    help="Choose which laws apply to the organisation, and so what a search covers.",
    no_args_is_help=True,
)

EVERY_LAW = "No laws are selected, so every search covers every loaded law."


@app.command(name="list")
def list_() -> None:
    """List the loaded laws and which of them a search covers."""
    with session_scope(load_settings()) as session:
        selected = selected_laws(session)
        for pack in loaded_laws(session):
            covered = selected is None or pack.slug in selected
            typer.echo(f"{pack.slug:16} {'searched' if covered else '-':9} {pack.name}")
    if selected is None:
        typer.echo(f"\n{EVERY_LAW} Choose with: dpolens laws select <slug>")


@app.command()
def select(
    slugs: Annotated[list[str], typer.Argument(help="The laws that apply, by slug")],
) -> None:
    """Make these exactly the laws that apply. Written to the governance log."""
    with session_scope(load_settings()) as session:
        chosen = select_laws(session, slugs, actor=cli_actor())
    typer.echo(f"Selected: {', '.join(chosen)}. A search covers these unless it names others.")


@app.command()
def clear() -> None:
    """Go back to searching every loaded law. Written to the governance log."""
    with session_scope(load_settings()) as session:
        clear_selection(session, actor=cli_actor())
    typer.echo(EVERY_LAW)
