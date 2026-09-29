"""Governance log commands: read it, verify it, hand it to an auditor.

Nothing runs `verify` on a schedule in this release. The operator documentation
says when to run it, because a scheduled check wants somewhere to raise an alarm
and that is a later feature.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dpolens.engine.logs.export import export, verify_export
from dpolens.engine.logs.governance import cli_actor, read_entries, verify
from dpolens.engine.session import governance_log_is_append_only, session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="governance", help="Read, verify and export the governance log.", no_args_is_help=True
)


@app.command(name="list")
def list_(
    limit: Annotated[int, typer.Option(help="How many of the most recent entries to show")] = 20,
) -> None:
    """Show the most recent entries, newest last."""
    settings = load_settings()
    with session_scope(settings) as session:
        entries = read_entries(session)
        if not entries:
            typer.echo("The governance log is empty.")
            return
        for row in entries[-limit:]:
            actor = str(row.actor_user_id) if row.actor_user_id else "no user (see details)"
            typer.echo(
                f"{row.seq:>6}  {row.occurred_at.isoformat()}  {row.action}  "
                f"{row.target_type}:{row.target_id}  actor {actor}"
            )
            typer.echo(f"        {row.details_text}")


@app.command(name="verify")
def verify_(
    directory: Annotated[
        Path | None,
        typer.Option("--export", help="Verify an exported directory instead of the database"),
    ] = None,
) -> None:
    """Recompute the chain and report the first thing that is wrong."""
    if directory is not None:
        report = verify_export(directory)
    else:
        settings = load_settings()
        with session_scope(settings) as session:
            report = verify(session)
            # Verification proves the rows have not been edited. It says nothing
            # about whether they could be, and that is worth knowing here.
            if not governance_log_is_append_only(session.connection()):
                typer.secho(
                    "This connection can change the governance log, so the chain is only "
                    "as good as the people holding these credentials. An instance serving "
                    "other people should connect as an application role with INSERT and "
                    "SELECT only.",
                    fg=typer.colors.YELLOW,
                )

    where = f"{directory}" if directory is not None else "the database"
    if not report.anchored_to_genesis:
        typer.echo(
            "This range does not reach the first entry ever written, so it was checked "
            "from its own first entry onwards."
        )
    if report.ok:
        typer.echo(f"Verified {report.entries} entries in {where}.")
        return

    if report.out_of_order:
        typer.echo("The chain links entries in a different order than their sequence numbers.")
        typer.echo(f"  chain order: {', '.join(str(seq) for seq in report.out_of_order)}")
    if report.first_broken_seq is not None:
        typer.echo(f"Entry {report.first_broken_seq} is wrong: {report.reason}")
    raise typer.Exit(code=1)


@app.command(name="export")
def export_(
    directory: Annotated[Path, typer.Argument(help="An empty or new directory to write into")],
    from_seq: Annotated[int | None, typer.Option(help="First entry to include")] = None,
    to_seq: Annotated[int | None, typer.Option(help="Last entry to include")] = None,
) -> None:
    """Write entries.jsonl, manifest.json and actors.json, then verify them."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        report = export(session, directory, actor=actor, from_seq=from_seq, to_seq=to_seq)

    typer.echo(f"Wrote {report.entries} entries to {directory}")
    if not report.anchored_to_genesis:
        typer.echo(
            "  This range does not start at the first entry ever written. The manifest "
            "says so, and a verifier will repeat it."
        )
    if report.ok:
        typer.echo("  Verified from the files alone.")
        return
    typer.echo(f"  The export does not verify: {report.reason}")
    raise typer.Exit(code=1)
