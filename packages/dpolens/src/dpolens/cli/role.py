"""Role commands: freely named bundles of catalog permissions."""

from __future__ import annotations

from typing import Annotated

import typer

from dpolens.cli import ask
from dpolens.cli.ask import Asking
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.permissions import PERMISSIONS
from dpolens.engine.auth.roles import (
    create_role,
    delete_role,
    grant_permission,
    holders,
    list_roles,
    revoke_permission,
)
from dpolens.engine.auth.users import get_role
from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="role", help="Create roles and change what they allow.", no_args_is_help=True
)


@app.command(name="list")
def list_() -> None:
    """List roles, what they allow, and who holds them."""
    settings = load_settings()
    with session_scope(settings) as session:
        bootstrap(session, actor=cli_actor())
        for role in list_roles(session):
            held_by = holders(session, role)
            seeded = " (seeded)" if role.is_seeded else ""
            typer.echo(f"{role.name}{seeded}: {role.description}")
            typer.echo(f"  permissions: {', '.join(sorted(role.permission_keys())) or 'none'}")
            typer.echo(f"  held by: {', '.join(user.email for user in held_by) or 'nobody'}")


@app.command()
def permissions() -> None:
    """Print the permission catalog, which is defined in code."""
    for key, description in sorted(PERMISSIONS.items()):
        typer.echo(f"{key:28} {description}")


@app.command(cls=Asking)
def create(
    name: Annotated[str, typer.Argument(help="Name of the new role")],
    permission: Annotated[
        list[str] | None,
        typer.Option(help="Permission to include, repeatable. Left out, a checklist in a terminal"),
    ] = None,
    description: Annotated[str, typer.Option(help="What this role is for")] = "",
) -> None:
    """Create a role."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        if permission is None and ask.interactive():
            permission = ask.checklist(
                "What it allows",
                [(key, f"{key}, {meaning}") for key, meaning in PERMISSIONS.items()],
            )
        role = create_role(
            session,
            name=name,
            actor=actor,
            description=description,
            permissions=tuple(permission or ()),
        )
        typer.echo(f"Created {role.name} with {len(role.permissions)} permissions")


@app.command(cls=Asking)
def grant(
    name: Annotated[str, typer.Argument(help="Which role")],
    permission: Annotated[str, typer.Argument(help="Which permission to add")],
) -> None:
    """Add a permission to a role."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        role = grant_permission(session, role_name=name, permission=permission, actor=actor)
        typer.echo(f"{role.name}: {', '.join(sorted(role.permission_keys()))}")


@app.command(cls=Asking)
def revoke(
    name: Annotated[str, typer.Argument(help="Which role")],
    permission: Annotated[str, typer.Argument(help="Which permission to remove")],
) -> None:
    """Remove a permission from a role."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        role = revoke_permission(session, role_name=name, permission=permission, actor=actor)
        typer.echo(f"{role.name}: {', '.join(sorted(role.permission_keys())) or 'none'}")


@app.command(cls=Asking)
def delete(name: Annotated[str, typer.Argument(help="Which role to delete")]) -> None:
    """Delete a role nobody holds."""
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        get_role(session, name)
        delete_role(session, role_name=name, actor=actor)
        typer.echo(f"Deleted {name}")
