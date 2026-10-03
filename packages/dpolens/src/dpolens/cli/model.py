"""Model commands.

The embedding model is the only thing DPOLens downloads, and it does it once.
Everything after that runs with no network at all, which is the promise this
command exists to make keepable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dpolens.engine.embedding import DEFAULT_MODEL, MODELS, get_model
from dpolens.engine.embedding.encode import fetch

app = typer.Typer(name="model", help="Fetch and list embedding models.", no_args_is_help=True)


@app.command(name="fetch")
def fetch_(
    name: Annotated[str, typer.Option("--name", help="Which model to fetch")] = DEFAULT_MODEL,
    cache_dir: Annotated[
        Path | None, typer.Option(help="Where to keep the files, if not the default cache")
    ] = None,
) -> None:
    """Download a model, so that searching never has to.

    Running it again when the files are already there costs nothing.
    """
    model = get_model(name)
    typer.echo(f"Fetching {model.repo} ...")
    for path in fetch(model, cache_dir=cache_dir):
        typer.echo(f"  {path}")
    typer.echo(f"{model.name} is ready. Nothing else reaches the network.")


@app.command(name="list")
def list_() -> None:
    """List the models this version knows about."""
    for model in MODELS.values():
        default = "  (default)" if model.name == DEFAULT_MODEL else ""
        typer.echo(f"{model.name}  {model.dimensions} dimensions  {model.repo}{default}")
        if model.note:
            typer.echo(f"    {model.note}")
