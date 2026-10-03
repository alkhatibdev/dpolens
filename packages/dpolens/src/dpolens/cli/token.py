"""Token commands.

Creating a token is the third thing an operator does on a fresh instance, after
starting it and creating a user, because until the dashboard exists a token is
the only way a surface reaches the corpus.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.surface import SURFACE_EMAIL, SURFACE_NAME, ensure_surface
from dpolens.engine.auth.tokens import list_tokens, mint, revoke, status_of
from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

SURFACE_PATH = Path("/run/dpolens/surface-token")
"""Where a container writes the credential its MCP server reads."""

app = typer.Typer(
    name="token", help="Create, list and revoke personal access tokens.", no_args_is_help=True
)


@app.command()
def create(
    email: Annotated[str, typer.Option(help="Whose token this is")],
    name: Annotated[str, typer.Option(help="What it is for, such as laptop or CI")],
    permission: Annotated[
        list[str] | None,
        typer.Option(help="Permission to carry, repeatable. Must be one its owner holds"),
    ] = None,
    expires_in_days: Annotated[
        int | None, typer.Option(help="Expire after this many days (default: until revoked)")
    ] = None,
    trusted_surface: Annotated[
        bool,
        typer.Option(
            "--trusted-surface",
            help="May act on behalf of other users. For a surface, never for a person",
        ),
    ] = False,
) -> None:
    """Create a token and print it once."""
    settings = load_settings()
    actor = cli_actor()
    expires_at = datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None

    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        row, token = mint(
            session,
            email=email,
            name=name,
            permissions=tuple(permission or ()),
            actor=actor,
            expires_at=expires_at,
            trusted_surface=trusted_surface,
        )
        held = ", ".join(row.permissions) or "nothing, so it can do nothing"

        typer.echo(f"Created {row.prefix}... for {email}: {row.name}")
        typer.echo(f"  permissions: {held}")
        typer.echo(f"  expires: {row.expires_at.date() if row.expires_at else 'when revoked'}")
        if trusted_surface:
            typer.echo("  trusted surface: may act on behalf of other users")
        typer.secho(f"\n{token}", bold=True)
        typer.secho(
            "This is the only time the token is shown. Nothing stores it, only its hash.",
            fg=typer.colors.YELLOW,
        )


@app.command(name="list")
def list_(
    email: Annotated[str | None, typer.Option(help="Only this user's tokens")] = None,
) -> None:
    """List tokens by prefix, with what each one may do and whether it still works."""
    settings = load_settings()
    with session_scope(settings) as session:
        bootstrap(session, actor=cli_actor())
        tokens = list_tokens(session, email=email)
        if not tokens:
            typer.echo("No tokens yet. `dpolens token create` makes one.")
            return
        for row in tokens:
            used = row.last_used_at.isoformat(timespec="seconds") if row.last_used_at else "never"
            surface = "  [trusted surface]" if row.trusted_surface else ""
            typer.echo(
                f"{row.prefix}  {row.owner.email}  {row.name}  [{status_of(row)}]  "
                f"last used {used}{surface}"
            )
            typer.echo(f"    permissions: {', '.join(row.permissions) or 'none'}")


@app.command(name="revoke")
def revoke_(
    prefix: Annotated[str, typer.Argument(help="The prefix `token list` prints")],
) -> None:
    """Stop a token working, keeping the row so the logs still point at it."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        row = revoke(session, prefix=prefix, actor=actor)
        typer.echo(f"{row.prefix} is revoked. It stops working on its next call.")


@app.command(name="ensure-surface")
def ensure_surface_(
    out: Annotated[
        Path, typer.Option(help="Where to write the credential, for a surface to read")
    ] = SURFACE_PATH,
    name: Annotated[str, typer.Option(help="What the credential is for")] = SURFACE_NAME,
    email: Annotated[
        str,
        typer.Option(help="The service account the credential belongs to. One per surface"),
    ] = SURFACE_EMAIL,
) -> None:
    """Make sure a surface credential exists on disk, minting one if it does not.

    Run on every start. A credential that still works is left alone, and a new
    one supersedes whatever the service account held before, because a secret
    that is no longer on disk cannot be recovered from the database.

    The credential is never printed. It is written to the file, with a mode only
    its owner can read, and a surface reads it from there.
    """
    settings = load_settings()
    actor = cli_actor()

    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        done = ensure_surface(session, path=out, actor=actor, name=name, email=email)

    if done.minted:
        typer.echo(f"Wrote a surface credential to {done.path}: {done.prefix}...")
        typer.echo("Any credential the service account held before it no longer works.")
    else:
        typer.echo(f"The surface credential at {done.path} still works: {done.prefix}...")
