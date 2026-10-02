"""Query log commands.

The instance purges expired questions itself, once a day. This is here for an
operator who wants it to happen now, or who runs the purge from outside.
"""

from __future__ import annotations

import typer

from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.logs.queries import count_entries, purge_expired
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="queries",
    help="The query log: what has been asked, and for how long.",
    no_args_is_help=True,
)


@app.command()
def purge() -> None:
    """Delete the questions whose retention has run out."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        deleted = purge_expired(session, actor=actor)
        remaining = count_entries(session)

    if deleted:
        typer.echo(f"Deleted {deleted} expired entries, {remaining} left.")
    else:
        typer.echo(f"Nothing had expired. {remaining} entries are kept.")


@app.command()
def status() -> None:
    """How many questions are kept, and for how long they will be."""
    settings = load_settings()
    with session_scope(settings) as session:
        kept = count_entries(session)

    typer.echo(f"{kept} entries kept, retention {settings.query_log_retention_days} days.")
    typer.echo("Questions are stored with personal data redacted, and deleted when they expire.")
