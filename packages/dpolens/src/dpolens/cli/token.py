"""Token commands.

Creating a token is the third thing an operator does on a fresh instance, after
starting it and creating a user, because until the dashboard exists a token is
the only way a surface reaches the corpus.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.tokens import list_tokens, mint, revoke, status_of
from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

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
