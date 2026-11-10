"""Search question commands: load a law's questions, and turn their use in search on or off."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.search.questions import (
    load_questions,
    loaded_files,
    questions_on,
    switch_questions,
)
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="search-questions",
    help="The questions written beside each clause, which help search order what it found.",
    no_args_is_help=True,
)


@app.command()
def load(
    files: Annotated[
        list[Path],
        typer.Argument(
            help="A law's file, such as search-questions/gdpr.yaml", exists=True, dir_okay=False
        ),
    ],
) -> None:
    """Load a law's search questions, in place of the ones it had. Written to the governance log."""
    with session_scope(load_settings()) as session:
        for file in files:
            loaded = load_questions(session, file, actor=cli_actor())
            done = "already loaded" if loaded.unchanged else f"loaded {loaded.questions} questions"
            typer.echo(
                f"{loaded.pack}: {done}, {loaded.current} of them beside the words they were "
                "written for"
            )


@app.command()
def on() -> None:
    """Use the search questions in every search. Written to the governance log."""
    with session_scope(load_settings()) as session:
        switch_questions(session, True, actor=cli_actor())
    typer.echo("Searches use the search questions.")


@app.command()
def off() -> None:
    """Search without the search questions. Written to the governance log."""
    with session_scope(load_settings()) as session:
        switch_questions(session, False, actor=cli_actor())
    typer.echo("Searches no longer use the search questions.")


@app.command()
def status() -> None:
    """Whether searches use the questions, and which laws have them."""
    with session_scope(load_settings()) as session:
        on = questions_on(session)
        files = loaded_files(session)
    typer.echo(f"Searches {'use' if on else 'do not use'} the search questions.")
    for file in files:
        typer.echo(
            f"{file.pack:16} {file.current} of {file.questions} current, written by "
            f"{file.written_by} on {file.written_on}, checked by {file.checked_by}"
        )
    if not files:
        typer.echo("No law has search questions loaded: dpolens search-questions load")
