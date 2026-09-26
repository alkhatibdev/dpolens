"""Entry point for the `dpolens` command."""

from __future__ import annotations

import typer

from dpolens import __version__
from dpolens.cli import clause, evals, index, pack, search
from dpolens.engine.documents.read import ClauseNotFound
from dpolens.engine.packs.format import PackFormatError
from dpolens.engine.session import MissingExtension, NotMigrated

EXPECTED = (MissingExtension, NotMigrated, ClauseNotFound, PackFormatError)

app = typer.Typer(
    name="dpolens",
    help="Grounds AI coding assistants in your organisation's policies and the law.",
    no_args_is_help=True,
)


app.add_typer(pack.app)
app.add_typer(clause.app)
app.add_typer(index.app)
app.add_typer(evals.app)
app.command(name="search")(search.run)


@app.callback()
def cli() -> None:
    """Commands are grouped noun then verb: `dpolens pack load`, `dpolens clause show`."""


@app.command()
def version() -> None:
    """Print the DPOLens version."""
    typer.echo(__version__)


def main() -> None:
    try:
        app()
    except EXPECTED as problem:
        typer.secho(str(problem), fg=typer.colors.RED, err=True)
        raise SystemExit(1) from problem
