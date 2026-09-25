"""Searching the corpus from the command line."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dpolens.cli.clause import print_clause
from dpolens.engine.embedding import DEFAULT_MODEL, Embedder, get_model
from dpolens.engine.search import Fusion, search
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

SNIPPET = 400
"""Search shows enough to judge a result. `dpolens clause show` gives the rest."""


def run(
    query: Annotated[str, typer.Argument(help="A question, in your own words")],
    limit: Annotated[int, typer.Option(help="How many clauses to return")] = 5,
    expand: Annotated[str, typer.Option(help="none, siblings or parent")] = "none",
    fusion: Annotated[str, typer.Option(help="rrf:10, rrf:60 or convex:0.5")] = "rrf:10",
    model: Annotated[str, typer.Option(help="Embedding model")] = DEFAULT_MODEL,
    cache_dir: Annotated[Path | None, typer.Option(help="Where model files are kept")] = None,
    explain: Annotated[bool, typer.Option(help="Show which retriever found what")] = False,
) -> None:
    """Search the loaded law packs and policies."""
    with (
        Embedder(get_model(model), cache_dir=cache_dir) as embedder,
        session_scope(load_settings()) as session,
    ):
        results = search(
            session,
            embedder,
            query,
            limit=limit,
            expand=expand,  # type: ignore[arg-type]
            fusion=Fusion.parse(fusion),
        )

        if not results:
            typer.secho("Nothing in the loaded documents matches that.", fg=typer.colors.YELLOW)
            return

        for position, result in enumerate(results, start=1):
            trail = " > ".join(
                parent.heading or parent.label or parent.key for parent in result.breadcrumb
            )
            typer.echo("")
            typer.secho(
                f"{position}. {result.clause.document_slug}  {trail}".rstrip(),
                fg=typer.colors.BRIGHT_BLACK,
            )
            print_clause(result.clause, indent=0, snippet=SNIPPET)
            if explain:
                found = ", ".join(f"{name} #{rank}" for name, rank in sorted(result.ranks.items()))
                typer.secho(f"   score {result.score:.4f}  ({found})", fg=typer.colors.BRIGHT_BLACK)
            for extra in result.expanded:
                print_clause(extra, indent=1, snippet=SNIPPET)
