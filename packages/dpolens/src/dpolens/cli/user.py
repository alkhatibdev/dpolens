"""User commands.

Creating the first user is the second thing an operator does, after
`docker compose up`, because until the dashboard exists a personal access token
is the only way in.
"""

from __future__ import annotations

from typing import Annotated

import typer

from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.users import (
    activate,
    create_user,
    deactivate,
    grant_role,
    list_users,
    managers,
    revoke_role,
)
from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(name="user", help="Create users and manage their roles.", no_args_is_help=True)


@app.command()
def create(
    email: Annotated[str, typer.Option(help="Email address, which is the login name")],
    name: Annotated[str, typer.Option(help="Display name, shown in the logs")],
    role: Annotated[
        list[str] | None, typer.Option(help="Role to hold, repeatable (default: none)")
    ] = None,
    service: Annotated[
        bool, typer.Option("--service", help="Create a service account rather than a person")
    ] = False,
) -> None:
    """Create a user. A service account cannot sign in and owns tokens instead."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        user = create_user(
            session,
            email=email,
            display_name=name,
            actor=actor,
            kind="service_account" if service else "person",
            roles=tuple(role or ()),
        )
        typer.echo(f"Created {user.email} ({user.kind}) with id {user.id}")
        if user.roles:
            typer.echo(f"  roles: {', '.join(held.name for held in user.roles)}")
        else:
            typer.echo("  roles: none yet, so this user can do nothing. Use `dpolens user grant`.")


@app.command(name="list")
def list_() -> None:
    """List users, their roles and their status."""
    settings = load_settings()
    with session_scope(settings) as session:
        bootstrap(session, actor=cli_actor())
        users = list_users(session)
        if not users:
            typer.echo("No users yet. `dpolens user create` makes the first one.")
            return
        for user in users:
            roles = ", ".join(role.name for role in user.roles) or "none"
            typer.echo(f"{user.email}  [{user.status}]  {user.kind}  roles: {roles}")


@app.command()
def grant(
    email: Annotated[str, typer.Argument(help="Who gets the role")],
    role: Annotated[str, typer.Argument(help="Which role they get")],
) -> None:
    """Give a user a role."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        user = grant_role(session, email=email, role_name=role, actor=actor)
        typer.echo(f"{user.email} now holds: {', '.join(held.name for held in user.roles)}")


@app.command()
def revoke(
    email: Annotated[str, typer.Argument(help="Who loses the role")],
    role: Annotated[str, typer.Argument(help="Which role they lose")],
) -> None:
    """Take a role away from a user."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        user = revoke_role(session, email=email, role_name=role, actor=actor)
        remaining = ", ".join(held.name for held in user.roles) or "none"
        typer.echo(f"{user.email} now holds: {remaining}")


@app.command(name="deactivate")
def deactivate_(
    email: Annotated[str, typer.Argument(help="Whose access to block")],
) -> None:
    """Block a user's access, keeping the row so the logs still name them."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        user = deactivate(session, email=email, actor=actor)
        typer.echo(f"{user.email} is deactivated. Their tokens stop working with them.")


@app.command(name="activate")
def activate_(email: Annotated[str, typer.Argument(help="Whose access to restore")]) -> None:
    """Let a deactivated user back in, with the roles they had."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        user = activate(session, email=email, actor=actor)
        typer.echo(f"{user.email} is active again")


@app.command()
def admins() -> None:
    """Who can still manage roles. This is what the lockout guard protects."""
    settings = load_settings()
    with session_scope(settings) as session:
        bootstrap(session, actor=cli_actor())
        people = managers(session)
        if not people:
            typer.echo("Nobody can manage roles. That should be impossible; report it.")
            return
        for user in people:
            typer.echo(user.email)
