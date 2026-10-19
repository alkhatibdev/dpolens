"""Query log commands.

Questions are kept unless DPOLENS_QUERY_LOG_RETENTION_DAYS is set. Where it is, the
instance deletes what is past it itself, once a day. This is here for an operator who
wants that to happen now, or who runs it from outside.
"""

from __future__ import annotations

import typer

from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.logs.queries import count_entries, purge_expired
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

KEEPING = "Set DPOLENS_QUERY_LOG_RETENTION_DAYS to delete them after a number of days."

app = typer.Typer(
    name="queries",
    help="The query log: what has been asked, and for how long.",
    no_args_is_help=True,
)


@app.command()
def purge() -> None:
    """Delete the questions asked longer ago than the retention, when one is set."""
    settings = load_settings()
    days = settings.query_log_retention_days
    if days is None:
        typer.echo(f"Questions are kept, so nothing was deleted. {KEEPING}")
        return
    with session_scope(settings) as session:
        deleted = purge_expired(session, retention_days=days, actor=cli_actor())
        remaining = count_entries(session)

    if deleted:
        typer.echo(f"Deleted {deleted} entries asked more than {days} days ago, {remaining} left.")
    else:
        typer.echo(f"Nothing was asked more than {days} days ago. {remaining} entries are kept.")


@app.command()
def status() -> None:
    """How many questions are kept, and for how long they will be."""
    settings = load_settings()
    with session_scope(settings) as session:
        kept = count_entries(session)

    days = settings.query_log_retention_days
    if days is None:
        typer.echo(f"{kept} entries kept, with no retention set. {KEEPING}")
    else:
        typer.echo(f"{kept} entries kept, each deleted {days} days after it was asked.")
    typer.echo("Questions are stored with personal data redacted.")
