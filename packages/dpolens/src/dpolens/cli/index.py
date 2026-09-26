"""Building and inspecting the vector index."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import text

from dpolens.engine.embedding import DEFAULT_MODEL, Embedder, get_model
from dpolens.engine.embedding.index import build_index
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(name="index", help="Build and inspect the vector index.", no_args_is_help=True)


@app.command()
def build(
    model: Annotated[str, typer.Option(help="Embedding model to use")] = DEFAULT_MODEL,
    cache_dir: Annotated[Path | None, typer.Option(help="Where model files are kept")] = None,
) -> None:
    """Embed every clause that has text.

    The first run downloads the model, which is the only time DPOLens reaches
    the network. After that it works offline.
    """
    typer.echo(f"Loading {model} ...")
    started = time.time()
    with (
        Embedder(get_model(model), cache_dir=cache_dir) as embedder,
        session_scope(load_settings()) as session,
    ):
        result = build_index(session, embedder)
    elapsed = time.time() - started

    typer.echo(
        f"Embedded {result.embedded} clauses with {result.model} "
        f"({result.recipe}) in {elapsed:.1f}s, "
        f"skipping {result.skipped_without_text} with no text of their own"
    )


@app.command()
def status() -> None:
    """Show which model is active and how much of the corpus it covers."""
    with session_scope(load_settings()) as session:
        rows = session.execute(
            text(
                """
                SELECT m.name, m.dimensions, m.is_active, count(e.node_text_id) AS vectors,
                       min(e.context_recipe) AS recipe
                FROM embedding_models m
                LEFT JOIN node_embeddings e ON e.embedding_model_id = m.id
                GROUP BY m.id, m.name, m.dimensions, m.is_active
                ORDER BY m.name
                """
            )
        ).all()
        embeddable = session.execute(
            text("SELECT count(*) FROM node_texts WHERE length(trim(body_text)) > 0")
        ).scalar_one()

    if not rows:
        typer.echo("Nothing indexed yet. Run `dpolens index build`.")
        return

    typer.echo(f"{embeddable} clauses have text and can be embedded\n")
    for row in rows:
        marker = "active" if row.is_active else "      "
        typer.echo(
            f"  {marker}  {row.name:18} {row.dimensions:>4}d  "
            f"{row.vectors}/{embeddable} vectors  recipe {row.recipe or '-'}"
        )
