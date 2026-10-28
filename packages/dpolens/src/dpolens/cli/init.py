"""Setting up a new instance in one command.

`dpolens init` makes the first administrator, gives them a password for the
dashboard and asks which laws apply. It does only what is still missing, so running
it again is safe. In a terminal it asks; a script passes the same answers as flags.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer
from sqlalchemy.orm import Session

from dpolens.cli import ask
from dpolens.engine.auth.catalog import bootstrap
from dpolens.engine.auth.passwords import give_password
from dpolens.engine.auth.permissions import ADMIN
from dpolens.engine.auth.users import create_user, managers
from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.packs.selection import loaded_laws, select_laws, selected_laws
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings


def _password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    if ask.interactive():
        return ask.password()
    raise typer.BadParameter(
        "needed, and there is no terminal to ask in", param_hint="'--password-stdin'"
    )


def _laws(session: Session, given: list[str] | None) -> list[str]:
    if given:
        return given
    if ask.interactive():
        return ask.checklist(
            "Which laws apply to your organisation",
            [(pack.slug, f"{pack.name}, {pack.jurisdiction}") for pack in loaded_laws(session)],
            at_least_one=True,
        )
    raise typer.BadParameter("needed, and there is no terminal to ask in", param_hint="'--law'")


def run(
    email: Annotated[
        str | None, typer.Option(help="The first administrator's email address")
    ] = None,
    name: Annotated[str | None, typer.Option(help="Their name, as the logs show it")] = None,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read their password from standard input")
    ] = False,
    law: Annotated[
        list[str] | None, typer.Option(help="A law that applies, by slug, repeatable")
    ] = None,
) -> None:
    """Set up the instance: its first administrator, their password and the laws that apply.

    Run again, it does only what is still missing.
    """
    settings = load_settings()
    actor = cli_actor()
    with session_scope(settings) as session:
        bootstrap(session, actor=actor)
        administrators = [user.email for user in managers(session)]
        created = None
        if not administrators:
            email = ask.needed(email, flag="--email", label="Your email address, to sign in with")
            name = ask.needed(name, flag="--name", label="Your name, as the logs show it")
            password = _password(password_stdin)
            user = create_user(session, email=email, display_name=name, actor=actor, roles=(ADMIN,))
            session.flush()
            give_password(session, user=user, password=password, actor=actor)
            created = user.email
            typer.echo(f"Created {created}, an administrator who can sign in to the dashboard.")

        chosen = selected_laws(session)
        newly_chosen = chosen is None and bool(loaded_laws(session))
        if newly_chosen:
            chosen = select_laws(session, _laws(session, law), actor=actor)
            # A community version holds the law alone, and answers anyone without a token.
            covered = "" if settings.community else " and your organisation's policies"
            typer.echo(f"Searches cover {', '.join(chosen)}{covered}.")

    if created or newly_chosen:
        sign_in = f" and sign in as {created}" if created else ""
        typer.echo(f"\nOpen the dashboard at {settings.public_dashboard_url}{sign_in}.")
        if settings.community:
            typer.echo(f"AI assistants connect to {settings.public_mcp_url} with no token.")
        else:
            typer.echo("Under Tokens, make the token your editor connects with.")
        return

    covered = ", ".join(chosen or ()) or "no law yet"
    typer.echo(
        f"This instance is set up: {', '.join(administrators)} can manage it, and searches "
        f"cover {covered}."
    )
    typer.echo("Add a person with: dpolens user create")
    typer.echo("Change the laws with: dpolens laws select")
